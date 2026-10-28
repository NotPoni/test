import time

import discord
from discord import app_commands
from discord.ext import commands

from utils import FieldsModal, admin_only, deny, embed, is_admin_member


async def event_embed(db, ev):
    n = (await db.one("SELECT COUNT(*) AS c FROM event_regs WHERE event_id=?", ev["id"]))["c"]
    title = "РП мероприятие" if ev["kind"] == "rp" else "Мероприятие"
    e = embed(f"{title}: {ev['name']}", "🟢 Регистрация открыта" if ev["is_open"] else "🔴 Закрыто")
    e.add_field(name="Участников", value=str(n))
    e.add_field(name="Организатор", value=f"<@{ev['created_by']}>")
    return e


async def panel_embed(db):
    evs = await db.all("SELECT * FROM events WHERE is_open=1 ORDER BY id DESC LIMIT 10")
    e = embed("Панель управления ивентами", f"**Регистрация:** {'🟢 есть активные' if evs else '🔴 нет'}")
    e.add_field(
        name="Активные мероприятия",
        value="\n".join(f"#{r['id']} {r['name']} ({r['kind']})" for r in evs) or "Сейчас нет активных мероприятий.",
        inline=False)
    return e


async def close_event(bot, ev):
    await bot.db.run("UPDATE events SET is_open=0 WHERE id=?", ev["id"])
    ch = bot.get_channel(ev["channel_id"])
    if ch and ev["message_id"]:
        try:
            msg = await ch.fetch_message(ev["message_id"])
            fresh = await bot.db.one("SELECT * FROM events WHERE id=?", ev["id"])
            await msg.edit(embed=await event_embed(bot.db, fresh), view=None)
        except discord.HTTPException:
            pass


async def pick_event(i, cb, only_open=True):
    db = i.client.db
    q = "SELECT * FROM events" + (" WHERE is_open=1" if only_open else "") + " ORDER BY id DESC LIMIT 25"
    rows = await db.all(q)
    if not rows:
        return await deny(i, "Мероприятий нет.")
    v = discord.ui.View(timeout=120)
    sel = discord.ui.Select(placeholder="Выберите мероприятие", options=[
        discord.SelectOption(label=f"#{r['id']} {r['name']}"[:100], value=str(r["id"])) for r in rows])

    async def on_pick(inter):
        ev = await db.one("SELECT * FROM events WHERE id=?", int(sel.values[0]))
        await cb(inter, ev)

    sel.callback = on_pick
    v.add_item(sel)
    await i.response.send_message("Выберите:", view=v, ephemeral=True)


class JoinView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Записаться", style=discord.ButtonStyle.success, custom_id="ev:join")
    async def join(self, i, _):
        await self.toggle(i, True)

    @discord.ui.button(label="Выйти", style=discord.ButtonStyle.secondary, custom_id="ev:leave")
    async def leave(self, i, _):
        await self.toggle(i, False)

    async def toggle(self, i, join):
        db = i.client.db
        ev = await db.one("SELECT * FROM events WHERE message_id=?", i.message.id)
        if not ev or not ev["is_open"]:
            return await deny(i, "Регистрация закрыта.")
        if join:
            await db.run("INSERT OR IGNORE INTO event_regs VALUES(?,?)", ev["id"], i.user.id)
        else:
            await db.run("DELETE FROM event_regs WHERE event_id=? AND user_id=?", ev["id"], i.user.id)
        await i.response.edit_message(embed=await event_embed(db, ev))


SPEC = [
    ("Начать регистрацию", "ev:start", discord.ButtonStyle.primary),
    ("Закрыть событие", "ev:close", discord.ButtonStyle.secondary),
    ("Ветки", "ev:thread", discord.ButtonStyle.secondary),
    ("Проверить откаты", "ev:check", discord.ButtonStyle.secondary),
    ("Закрыть все", "ev:closeall", discord.ButtonStyle.danger),
    ("РП", "ev:rp", discord.ButtonStyle.secondary),
    ("Статистика РП", "ev:rpstats", discord.ButtonStyle.secondary),
]


class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for label, cid, style in SPEC:
            b = discord.ui.Button(label=label, custom_id=cid, style=style)
            b.callback = self.click
            self.add_item(b)

    async def click(self, i: discord.Interaction):
        if not is_admin_member(i.user):
            return await deny(i)
        cid, db, panel = i.data["custom_id"], i.client.db, i.message

        async def refresh():
            try:
                await panel.edit(embed=await panel_embed(db))
            except discord.HTTPException:
                pass

        if cid in ("ev:start", "ev:rp"):
            kind = "mp" if cid == "ev:start" else "rp"

            async def done(inter, f):
                cur = await db.run(
                    "INSERT INTO events(name,kind,channel_id,created_by,created) VALUES(?,?,?,?,?)",
                    f["name"], kind, inter.channel_id, inter.user.id, time.time())
                ev = await db.one("SELECT * FROM events WHERE id=?", cur.lastrowid)
                msg = await inter.channel.send(embed=await event_embed(db, ev), view=JoinView())
                await db.run("UPDATE events SET message_id=? WHERE id=?", msg.id, ev["id"])
                await inter.response.edit_message(embed=await panel_embed(db))

            return await i.response.send_modal(FieldsModal("Новое мероприятие", [("name", "Название")], done))

        if cid == "ev:closeall":
            for ev in await db.all("SELECT * FROM events WHERE is_open=1"):
                await close_event(i.client, ev)
            return await i.response.edit_message(embed=await panel_embed(db))

        if cid == "ev:close":
            async def cb(inter, ev):
                await close_event(inter.client, ev)
                await inter.response.send_message("Мероприятие закрыто.", ephemeral=True)
                await refresh()
            return await pick_event(i, cb)

        if cid == "ev:thread":
            async def cb(inter, ev):
                ch = inter.client.get_channel(ev["channel_id"])
                try:
                    msg = await ch.fetch_message(ev["message_id"])
                    th = await msg.create_thread(name=f"Откаты • {ev['name']}"[:100])
                    await inter.response.send_message(f"Ветка создана: {th.mention}", ephemeral=True)
                except (discord.HTTPException, AttributeError):
                    await inter.response.send_message("Не удалось создать ветку.", ephemeral=True)
            return await pick_event(i, cb, only_open=False)

        if cid == "ev:check":
            async def cb(inter, ev):
                regs = await db.all("SELECT user_id FROM event_regs WHERE event_id=?", ev["id"])
                lines = []
                for r in regs:
                    has = await db.one("SELECT 1 FROM rollbacks WHERE user_id=? AND ts>=?", r["user_id"], ev["created"])
                    lines.append(f"{'✅' if has else '❌'} <@{r['user_id']}>")
                await inter.response.send_message(
                    embed=embed(f"Откаты: {ev['name']}", "\n".join(lines)[:3900] or "Никто не записался."), ephemeral=True)
            return await pick_event(i, cb, only_open=False)

        if cid == "ev:rpstats":
            n = (await db.one("SELECT COUNT(*) AS c FROM events WHERE kind='rp'"))["c"]
            p = (await db.one(
                "SELECT COUNT(*) AS c FROM event_regs WHERE event_id IN (SELECT id FROM events WHERE kind='rp')"))["c"]
            await i.response.send_message(embed=embed("Статистика РП", f"Мероприятий: **{n}**\nЗаписей участников: **{p}**"), ephemeral=True)


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(PanelView())
        self.bot.add_view(JoinView())

    @app_commands.command(name="panel_events", description="Панель создания ивентов")
    @admin_only()
    async def panel(self, i: discord.Interaction):
        await i.response.send_message(embed=await panel_embed(self.bot.db), view=PanelView())


async def setup(bot):
    await bot.add_cog(Events(bot))
