import json
import time

import discord
from discord import app_commands
from discord.ext import commands

from config import cfg
from utils import FieldsModal, admin_only, deny, embed, has_any_role, is_admin_member, send_to, to_int, parse_id

DEFAULT_QUESTIONS = [
    "Ник и статик",
    "Ссылка на откаты",
    "Средний урон за неделю",
    "Почему вас стоит повысить?",
]
COOLDOWN_DAYS = 3  # кулдаун после отказа
KINDS = {
    "tier": ["Tier I", "Tier II", "Tier III"],
    "sub": ["Rec", "Tch", "High"],
    "mcl": ["MCL Test"],
}


def role_for(kind, target):
    try:
        if kind == "tier":
            return cfg.tier_role_ids[KINDS["tier"].index(target)]
        if kind == "sub":
            return cfg.subdivision_role_ids[KINDS["sub"].index(target)]
    except IndexError:
        return 0
    return cfg.mcl_role_id


async def get_questions(db):
    rows = await db.all("SELECT id, text FROM app_questions ORDER BY id")
    if not rows:
        for q in DEFAULT_QUESTIONS:
            await db.run("INSERT INTO app_questions(text) VALUES(?)", q)
        rows = await db.all("SELECT id, text FROM app_questions ORDER BY id")
    return rows


class ApplyModal(discord.ui.Modal):
    def __init__(self, kind, target, questions):
        super().__init__(title=f"Заявка: {target}"[:45])
        self.kind, self.target = kind, target
        self.qs = []
        for q in questions[:5]:
            ti = discord.ui.TextInput(label=q["text"][:45], style=discord.TextStyle.paragraph, max_length=500)
            self.qs.append((q["text"], ti))
            self.add_item(ti)

    async def on_submit(self, i: discord.Interaction):
        bot, db = i.client, i.client.db
        answers = [(q, t.value) for q, t in self.qs]
        cur = await db.run(
            "INSERT INTO applications(user_id,kind,target,answers,created) VALUES(?,?,?,?,?)",
            i.user.id, self.kind, self.target, json.dumps(answers, ensure_ascii=False), time.time())
        app_id = cur.lastrowid
        e = embed(f"Заявка #{app_id}: {self.target}", f"От {i.user.mention}")
        for q, a in answers:
            e.add_field(name=q[:256], value=a[:1024], inline=False)
        msg = await send_to(bot, cfg.applications_channel_id, embed=e, view=ReviewView())
        if not msg:
            await db.run("DELETE FROM applications WHERE id=?", app_id)
            return await i.response.send_message("Канал заявок не настроен.", ephemeral=True)
        await db.run("UPDATE applications SET message_id=? WHERE id=?", msg.id, app_id)
        await i.response.send_message("Заявка отправлена на рассмотрение.", ephemeral=True)


class ReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Одобрить", style=discord.ButtonStyle.success, custom_id="app:ok")
    async def ok(self, i, _):
        await self.finish(i, True)

    @discord.ui.button(label="Отклонить", style=discord.ButtonStyle.danger, custom_id="app:no")
    async def no(self, i, _):
        await self.finish(i, False)

    async def finish(self, i: discord.Interaction, approved: bool):
        if not (is_admin_member(i.user) or has_any_role(i.user, cfg.recruiter_role_id, cfg.tierchecker_role_id)):
            return await deny(i)
        db = i.client.db
        app = await db.one("SELECT * FROM applications WHERE message_id=?", i.message.id)
        if not app or app["status"] != "pending":
            return await deny(i, "Заявка уже обработана.")
        status = "approved" if approved else "rejected"
        await db.run("UPDATE applications SET status=?, reviewer=? WHERE id=?", status, i.user.id, app["id"])
        kind = "recruiter" if app["kind"] == "sub" else "tierchecker"
        await db.run("INSERT INTO staff_actions VALUES(?,?,?,?)", i.user.id, kind, status, time.time())

        member = i.guild.get_member(app["user_id"])
        if approved and member:
            rid = role_for(app["kind"], app["target"])
            role = i.guild.get_role(rid) if rid else None
            if role:
                try:
                    await member.add_roles(role, reason=f"Заявка #{app['id']}")
                except discord.HTTPException:
                    pass
        if not approved:
            await db.run("INSERT OR REPLACE INTO cooldowns VALUES(?,?,?)",
                         app["user_id"], app["kind"], time.time() + COOLDOWN_DAYS * 86400)

        color = discord.Color.green() if approved else discord.Color.red()
        e = i.message.embeds[0]
        e.color = color
        e.add_field(name="Решение", value=f"{'✅ Одобрено' if approved else '❌ Отклонено'} — {i.user.mention}", inline=False)
        await i.response.edit_message(embed=e, view=None)

        res = embed("Результат повышения", f"Администрация рассмотрела вашу заявку на **{app['target']}**.", color=color.value)
        res.add_field(name="Участник", value=f"<@{app['user_id']}>")
        res.add_field(name="Статус", value="Одобрено" if approved else "Отклонено")
        res.add_field(name="Администратор", value=i.user.mention)
        res.add_field(name="Время", value=f"<t:{int(time.time())}:f>", inline=False)
        await send_to(i.client, cfg.notify_channel_id, content=f"<@{app['user_id']}>", embed=res)


async def start(i: discord.Interaction, kind, target):
    db = i.client.db
    if kind == "sub" and await db.get("apps_open", "1") != "1":
        return await deny(i, "Набор в подразделения сейчас закрыт.")
    cd = await db.one("SELECT until FROM cooldowns WHERE user_id=? AND kind=?", i.user.id, kind)
    if cd and cd["until"] > time.time():
        return await deny(i, f"Кулдаун закончится <t:{int(cd['until'])}:R>.")
    if await db.one("SELECT 1 FROM applications WHERE user_id=? AND target=? AND status='pending'", i.user.id, target):
        return await deny(i, "У вас уже есть заявка на рассмотрении.")
    await i.response.send_modal(ApplyModal(kind, target, await get_questions(db)))


async def choose(i: discord.Interaction, kind):
    v = discord.ui.View(timeout=120)
    sel = discord.ui.Select(placeholder="Выберите вариант",
                            options=[discord.SelectOption(label=t, value=t) for t in KINDS[kind]])

    async def cb(inter):
        await start(inter, kind, sel.values[0])

    sel.callback = cb
    v.add_item(sel)
    await i.response.send_message("Что подаём?", view=v, ephemeral=True)


class PromoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Заявки на Tier", custom_id="promo:tier", style=discord.ButtonStyle.primary)
    async def tier(self, i, _):
        await choose(i, "tier")

    @discord.ui.button(label="Заявки в подразделения", custom_id="promo:sub", style=discord.ButtonStyle.primary)
    async def sub(self, i, _):
        await choose(i, "sub")

    @discord.ui.button(label="MCL Test", custom_id="promo:mcl", style=discord.ButtonStyle.secondary)
    async def mcl(self, i, _):
        await start(i, "mcl", "MCL Test")


async def settings_embed(db):
    open_ = await db.get("apps_open", "1") == "1"
    n = len(await get_questions(db))
    e = embed("Управление заявками")
    e.add_field(name="Текущий статус набора", value="🟢 Открыт" if open_ else "🔴 Закрыт")
    e.add_field(name="Вопросов в форме", value=str(n))
    return e


class AppSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(custom_id="appset:act", placeholder="Выберите действие...", options=[
        discord.SelectOption(label="Добавить вопрос в форму", value="add"),
        discord.SelectOption(label="Посмотреть текущую форму", value="view"),
        discord.SelectOption(label="Удалить вопрос", value="del"),
        discord.SelectOption(label="Вкл/выкл приём заявок", value="toggle"),
        discord.SelectOption(label="Сбросить настройки формы", value="reset"),
        discord.SelectOption(label="Сбросить кулдаун участнику", value="cd"),
    ])
    async def act(self, i: discord.Interaction, sel: discord.ui.Select):
        if not is_admin_member(i.user):
            return await deny(i)
        db, v = i.client.db, sel.values[0]
        qs = await get_questions(db)
        if v == "add":
            if len(qs) >= 5:
                return await deny(i, "Максимум 5 вопросов (лимит формы Discord).")

            async def done(inter, f):
                await db.run("INSERT INTO app_questions(text) VALUES(?)", f["q"])
                await inter.response.send_message("Вопрос добавлен.", ephemeral=True)

            return await i.response.send_modal(FieldsModal("Новый вопрос", [("q", "Текст вопроса")], done))
        if v == "view":
            text = "\n".join(f"{n}. {q['text']}" for n, q in enumerate(qs, 1))
            return await i.response.send_message(embed=embed("Текущая форма", text), ephemeral=True)
        if v == "del":
            async def done(inter, f):
                n = to_int(f["n"])
                if not n or not 1 <= n <= len(qs) or len(qs) == 1:
                    return await inter.response.send_message("Неверный номер (или это последний вопрос).", ephemeral=True)
                await db.run("DELETE FROM app_questions WHERE id=?", qs[n - 1]["id"])
                await inter.response.send_message("Удалено.", ephemeral=True)

            return await i.response.send_modal(FieldsModal("Удалить вопрос", [("n", "Номер вопроса")], done))
        if v == "toggle":
            new = "0" if await db.get("apps_open", "1") == "1" else "1"
            await db.put("apps_open", new)
            return await i.response.edit_message(embed=await settings_embed(db))
        if v == "reset":
            await db.run("DELETE FROM app_questions")
            await get_questions(db)
            return await i.response.send_message("Форма сброшена к стандартной.", ephemeral=True)
        if v == "cd":
            async def done(inter, f):
                uid = parse_id(f["u"])
                if not uid:
                    return await inter.response.send_message("Неверный ID.", ephemeral=True)
                await db.run("DELETE FROM cooldowns WHERE user_id=?", uid)
                await inter.response.send_message("Кулдаун сброшен.", ephemeral=True)

            await i.response.send_modal(FieldsModal("Сброс кулдауна", [("u", "ID или @упоминание")], done))


class Applications(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        for v in (ReviewView(), PromoView(), AppSettingsView()):
            self.bot.add_view(v)

    @app_commands.command(name="panel_promotion", description="Центр заявок (Tier / подразделения / MCL)")
    @admin_only()
    async def promo(self, i: discord.Interaction):
        e = embed("Центр заявок", "Выберите нужный раздел — бот откроет форму заявки.")
        e.add_field(name="Заявки на Tier", value="Tier I / II / III. Критерии: откаты, урон, карта.", inline=False)
        e.add_field(name="Заявки в подразделения", value="Rec, Tch, High — рабочие роли.", inline=False)
        e.add_field(name="Заявка в тестовый состав MCL", value="Нужны откаты с MCL/VZZ и арены.", inline=False)
        await i.response.send_message(embed=e, view=PromoView())

    @app_commands.command(name="panel_app_settings", description="Настройки заявок и кулдаунов")
    @admin_only()
    async def settings(self, i: discord.Interaction):
        await i.response.send_message(embed=await settings_embed(self.bot.db), view=AppSettingsView())


async def setup(bot):
    await bot.add_cog(Applications(bot))
