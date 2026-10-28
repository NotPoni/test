import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import cfg
from utils import FieldsModal, admin_only, deny, embed, send_to

WINDOW = 600  # окно подсчёта нарушений, сек

EVENTS = {
    "channel_delete": ("Удаление канала", "ban", 1),
    "channel_create": ("Создание канала", "ban", 1),
    "webhook_create": ("Создание вебхука", "ban", 1),
    "webhook_send": ("Отправка от вебхука", "kick", 1),
    "member_ban": ("Бан участника", "kick", 1),
    "member_kick": ("Кик участника", "kick", 1),
    "ping_everyone": ("Пинг everyone", "kick", 1),
    "ping_here": ("Пинг here", "kick", 1),
}
ACTIONS = {"ban": "Бан", "kick": "Кик", "none": "Без действий"}
AUDIT = {
    discord.AuditLogAction.channel_delete: "channel_delete",
    discord.AuditLogAction.channel_create: "channel_create",
    discord.AuditLogAction.webhook_create: "webhook_create",
    discord.AuditLogAction.ban: "member_ban",
    discord.AuditLogAction.kick: "member_kick",
}


async def build_embed(bot):
    rows = {r["event"]: r for r in await bot.db.all("SELECT * FROM protection")}
    lines = []
    for key, (name, _, _) in EVENTS.items():
        r = rows[key]
        act = ACTIONS[r["action"]]
        if r["action"] == "ban" and r["ban_hours"]:
            act = f"Врем. бан {r['ban_hours']}ч"
        lines.append(f"**{name}** — {act} • лимит `{r['limit_n']}`")
    e = embed("Панель управления защитой", "**Активные правила**\n" + "\n".join(lines))
    e.add_field(
        name="Термины",
        value="Бан — блокировка · Кик — исключение · Врем. бан — бан на N часов · Без действий — правило выключено",
        inline=False,
    )
    e.set_footer(text="Изменять настройки защиты может только владелец сервера")
    return e


class ProtectionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        custom_id="prot:event",
        placeholder="Выберите событие для настройки",
        options=[discord.SelectOption(label=v[0], value=k) for k, v in EVENTS.items()],
    )
    async def pick(self, i: discord.Interaction, sel: discord.ui.Select):
        if i.user.id != i.guild.owner_id:
            return await deny(i, "Только владелец сервера.")
        key = sel.values[0]

        async def done(inter, f):
            action = f["action"].lower()
            if action not in ACTIONS or not f["limit"].isdigit() or not f["hours"].isdigit():
                return await inter.response.send_message("Неверные значения.", ephemeral=True)
            await inter.client.db.run(
                "UPDATE protection SET action=?, limit_n=?, ban_hours=? WHERE event=?",
                action, max(1, int(f["limit"])), int(f["hours"]), key,
            )
            await inter.response.edit_message(embed=await build_embed(inter.client))

        await i.response.send_modal(FieldsModal(EVENTS[key][0], [
            ("action", "Действие: ban / kick / none"),
            ("limit", "Лимит срабатываний"),
            ("hours", "Часы бана (0 = навсегда)"),
        ], done))

    @discord.ui.button(label="Вайтлист", custom_id="prot:wl", style=discord.ButtonStyle.secondary)
    async def whitelist(self, i: discord.Interaction, _):
        if i.user.id != i.guild.owner_id:
            return await deny(i, "Только владелец сервера.")
        v = discord.ui.View(timeout=120)
        sel = discord.ui.UserSelect(placeholder="Добавить / убрать из вайтлиста")

        async def cb(inter):
            u = sel.values[0]
            db = inter.client.db
            if await db.one("SELECT 1 FROM whitelist WHERE user_id=?", u.id):
                await db.run("DELETE FROM whitelist WHERE user_id=?", u.id)
                txt = "убран из"
            else:
                await db.run("INSERT INTO whitelist VALUES(?)", u.id)
                txt = "добавлен в"
            await inter.response.send_message(f"{u.mention} {txt} вайтлист.", ephemeral=True)

        sel.callback = cb
        v.add_item(sel)
        await i.response.send_message("Выберите пользователя:", view=v, ephemeral=True)


class Protection(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        for k, (_, act, lim) in EVENTS.items():
            await self.bot.db.run(
                "INSERT OR IGNORE INTO protection(event,action,limit_n,ban_hours) VALUES(?,?,?,0)", k, act, lim)
        self.bot.add_view(ProtectionView())
        self.loop.start()

    async def cog_unload(self):
        self.loop.cancel()

    @app_commands.command(name="panel_protection", description="Панель защиты сервера")
    @admin_only()
    async def panel(self, i: discord.Interaction):
        await i.response.send_message(embed=await build_embed(self.bot), view=ProtectionView())

    async def punish(self, guild, user_id, event, detail=""):
        db = self.bot.db
        if user_id in (self.bot.user.id, guild.owner_id):
            return
        if await db.one("SELECT 1 FROM whitelist WHERE user_id=?", user_id):
            return
        rule = await db.one("SELECT * FROM protection WHERE event=?", event)
        if not rule or rule["action"] == "none":
            return
        now = time.time()
        await db.run("INSERT INTO protection_log VALUES(?,?,?)", user_id, event, now)
        c = await db.one(
            "SELECT COUNT(*) AS c FROM protection_log WHERE user_id=? AND event=? AND ts>?",
            user_id, event, now - WINDOW)
        if c["c"] < rule["limit_n"]:
            return
        reason = f"Защита: {EVENTS[event][0]} {detail}"[:480]
        result = "выполнено"
        try:
            if rule["action"] == "ban":
                await guild.ban(discord.Object(id=user_id), reason=reason, delete_message_seconds=0)
                if rule["ban_hours"]:
                    await db.run("INSERT OR REPLACE INTO temp_bans VALUES(?,?)",
                                 user_id, now + rule["ban_hours"] * 3600)
            else:
                await guild.kick(discord.Object(id=user_id), reason=reason)
        except discord.HTTPException as e:
            result = f"ошибка: {e}"
        await send_to(self.bot, cfg.log_channel_id, embed=embed(
            "🛡 Сработала защита",
            f"Пользователь: <@{user_id}>\nСобытие: **{EVENTS[event][0]}**\n"
            f"Наказание: **{rule['action']}** ({result})"))

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        ev = AUDIT.get(entry.action)
        if ev and entry.user_id and entry.guild.id == cfg.guild_id:
            await self.punish(entry.guild, entry.user_id, ev)

    @commands.Cog.listener()
    async def on_message(self, m: discord.Message):
        if not m.guild or m.guild.id != cfg.guild_id:
            return
        if m.webhook_id:
            try:
                wh = await m.fetch_webhook()
                if wh.user:
                    await self.punish(m.guild, wh.user.id, "webhook_send")
            except discord.HTTPException:
                pass
            return
        if m.author.bot:
            return
        if "@everyone" in m.content:
            await self.punish(m.guild, m.author.id, "ping_everyone")
        if "@here" in m.content:
            await self.punish(m.guild, m.author.id, "ping_here")

    @tasks.loop(minutes=1)
    async def loop(self):
        db = self.bot.db
        await db.run("DELETE FROM protection_log WHERE ts<?", time.time() - WINDOW)
        guild = self.bot.get_guild(cfg.guild_id)
        for r in await db.all("SELECT user_id FROM temp_bans WHERE until<?", time.time()):
            try:
                await guild.unban(discord.Object(id=r["user_id"]), reason="Истёк временный бан")
            except discord.HTTPException:
                pass
            await db.run("DELETE FROM temp_bans WHERE user_id=?", r["user_id"])

    @loop.before_loop
    async def _wait(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Protection(bot))
