"""Инактив-панель: AFK / Инактив / Вернулся / Модерация (по скриншоту) + предупреждения в #варны."""
import time
from datetime import datetime

import discord
from discord.ext import commands, tasks

import config
import ui
from checks import get_channel, get_role, is_staff, send_log
from utils import parse_minutes

DURATIONS = [("10 минут", 10), ("30 минут", 30), ("1 час", 60), ("3 часа", 180), ("6 часов", 360),
             ("12 часов", 720), ("1 день", 1440), ("3 дня", 4320), ("7 дней", 10080),
             ("14 дней", 20160), ("30 дней", 43200)]
MAX_MINUTES = 60 * 24 * 60
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря"]
PANEL_COLOR = 0x2B2D31


def fmt_date(ts: int) -> str:
    d = datetime.fromtimestamp(ts, config.TZ)
    return f"{d.day} {MONTHS[d.month - 1]}"


def fmt_left(ts: int) -> str:
    left = max(0, ts - int(time.time()))
    d, rest = divmod(left, 86400)
    h, rest = divmod(rest, 3600)
    m = rest // 60
    if d:
        return f"{d} дн. {h} ч."
    if h:
        return f"{h} ч. {m} мин."
    return f"{max(m, 1)} мин."


# ------------------------------------------------------------------ окна
class CustomModal(discord.ui.Modal, title="📝 Свой вариант AFK"):
    duration = discord.ui.TextInput(label="Длительность", placeholder="30, 2h, 3d, 1h30m", max_length=20)
    reason = discord.ui.TextInput(label="Причина", placeholder="Опционально", required=False, max_length=150)

    async def on_submit(self, interaction: discord.Interaction):
        minutes = parse_minutes(self.duration.value)
        if not minutes or minutes > MAX_MINUTES:
            return await interaction.response.send_message(
                embed=ui.err("Неверный формат. Примеры: `30`, `2h`, `3d`, `1h30m` (максимум 60 дней)."), ephemeral=True)
        await interaction.client.get_cog("AFK").start_afk(interaction, minutes, self.reason.value or None)


class InactiveModal(discord.ui.Modal, title="📝 Инактив"):
    reason = discord.ui.TextInput(label="Причина", placeholder="Отпуск, болезнь...",
                                  style=discord.TextStyle.paragraph, max_length=300)
    days = discord.ui.TextInput(label="Длительность (дни, 1–60)", placeholder="7", max_length=2)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.client.get_cog("AFK").request_inactive(interaction, self.days.value, self.reason.value)


class DurationSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="⏳ Выберите срок AFK",
                         options=[discord.SelectOption(label=l, value=str(m)) for l, m in DURATIONS])

    async def callback(self, interaction: discord.Interaction):
        await interaction.client.get_cog("AFK").start_afk(interaction, int(self.values[0]), None, edit=True)


class AFKChoiceView(discord.ui.View):
    """Кнопка «AFK»: выбор срока (видно только нажавшему)."""

    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(DurationSelect())

    @discord.ui.button(label="Свой вариант", emoji="📝", style=discord.ButtonStyle.primary)
    async def custom(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CustomModal())


class ForceReturnSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="👤 Снять AFK/Инактив у участника", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        user = self.values[0]
        ok = await interaction.client.get_cog("AFK").end_afk(interaction.guild, user.id, by=interaction.user)
        text = f"✅ Статус у <@{user.id}> снят." if ok else f"ℹ️ <@{user.id}> не в AFK/Инактиве."
        await interaction.response.edit_message(content=text, view=None)


class ModView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(ForceReturnSelect())

    @discord.ui.button(label="Обновить панель", emoji="🔄", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.client.get_cog("AFK").refresh_panel(interaction.guild)
        await interaction.response.edit_message(content="✅ Панель обновлена.", view=None)

    @discord.ui.button(label="Запросы на инактив", emoji="📋", style=discord.ButtonStyle.primary)
    async def pending(self, interaction: discord.Interaction, button: discord.ui.Button):
        g = interaction.guild
        rows = await interaction.client.db.fetchall(
            "SELECT * FROM afk WHERE guild_id=? AND kind='pending' ORDER BY until", g.id)
        ch = await get_channel(interaction.client, g, "ch_log_afk")
        lines = [f"• <@{r['user_id']}> — {r['reason'] or '—'}"
                 + (f" • [открыть](https://discord.com/channels/{g.id}/{ch.id}/{r['msg_id']})" if ch else "")
                 for r in rows]
        await interaction.response.edit_message(content="**Ожидают рассмотрения:**\n" + ("\n".join(lines) or "Нет запросов."),
                                                view=None)


# ------------------------------------------------------------------ панель
class AFKPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="AFK", emoji="🌙", style=discord.ButtonStyle.secondary, custom_id="afk:open", row=0)
    async def afk(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Выберите срок AFK:", view=AFKChoiceView(), ephemeral=True)

    @discord.ui.button(label="Инактив", emoji="🏖️", style=discord.ButtonStyle.secondary, custom_id="afk:inactive", row=0)
    async def inactive(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(InactiveModal())

    @discord.ui.button(label="Вернулся", emoji="🚪", style=discord.ButtonStyle.success, custom_id="afk:return", row=0)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await interaction.client.get_cog("AFK").end_afk(interaction.guild, interaction.user.id):
            await interaction.response.send_message(embed=ui.ok("С возвращением! Статус снят."), ephemeral=True)
        else:
            await interaction.response.send_message(embed=ui.err("Вы не в AFK/Инактиве."), ephemeral=True)

    @discord.ui.button(label="Модерация", emoji="⚙️", style=discord.ButtonStyle.secondary, custom_id="afk:mod", row=1)
    async def mod(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await is_staff(interaction):
            return await interaction.response.send_message(embed=ui.err("Только для сотрудников."), ephemeral=True)
        await interaction.response.send_message("⚙️ **Модерация инактива**", view=ModView(), ephemeral=True)


class InactiveReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _row(self, interaction):
        if not await is_staff(interaction):
            await interaction.response.send_message(embed=ui.err("Недостаточно прав."), ephemeral=True)
            return None
        row = await interaction.client.db.fetchone(
            "SELECT * FROM afk WHERE guild_id=? AND msg_id=? AND kind='pending'", interaction.guild_id, interaction.message.id)
        if not row:
            await interaction.response.send_message(embed=ui.err("Запрос уже обработан."), ephemeral=True)
        return row

    @discord.ui.button(label="Одобрить", emoji="✅", style=discord.ButtonStyle.success, custom_id="afk:ok")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await self._row(interaction)
        if not row:
            return
        cog = interaction.client.get_cog("AFK")
        await interaction.client.db.execute("UPDATE afk SET kind='inactive' WHERE guild_id=? AND user_id=?",
                                            row["guild_id"], row["user_id"])
        member = interaction.guild.get_member(row["user_id"])
        if member:
            await cog._role(member, "role_inactive", True)
            await cog._dm(member, "🏖️ Инактив одобрен", f"Ваш инактив одобрен до {fmt_date(row['until'])}.", config.COLOR_OK)
        emb = interaction.message.embeds[0].copy()
        emb.color = config.COLOR_OK
        emb.add_field(name="Решение", value=f"✅ Одобрил {interaction.user.mention}", inline=False)
        await interaction.response.edit_message(embed=emb, view=None)
        await cog.refresh_panel(interaction.guild)

    @discord.ui.button(label="Отклонить", emoji="❌", style=discord.ButtonStyle.danger, custom_id="afk:no")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await self._row(interaction)
        if not row:
            return
        cog = interaction.client.get_cog("AFK")
        await interaction.client.db.execute("DELETE FROM afk WHERE guild_id=? AND user_id=?", row["guild_id"], row["user_id"])
        member = interaction.guild.get_member(row["user_id"])
        if member:
            await cog._dm(member, "🏖️ Инактив отклонён", "Ваш запрос на инактив отклонён.", config.COLOR_ERR)
        emb = interaction.message.embeds[0].copy()
        emb.color = config.COLOR_ERR
        emb.add_field(name="Решение", value=f"❌ Отклонил {interaction.user.mention}", inline=False)
        await interaction.response.edit_message(embed=emb, view=None)


# ------------------------------------------------------------------ cog
class AFK(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.idle: dict[tuple, tuple] = {}   # (guild, user) -> (с какого времени, id канала)
        self.warned: set[tuple] = set()

    async def cog_load(self):
        self.bot.add_view(AFKPanelView())
        self.bot.add_view(InactiveReviewView())
        self.expire.start()
        if config.AFK_WARN_MINUTES > 0:
            self.warn_loop.start()

    def cog_unload(self):
        self.expire.cancel()
        self.warn_loop.cancel()

    async def _role(self, member: discord.Member, key: str, add: bool):
        role = await get_role(self.bot, member.guild, key)
        if not role:
            return
        try:
            if add:
                await member.add_roles(role, reason="AFK")
            else:
                await member.remove_roles(role, reason="AFK")
        except discord.Forbidden:
            pass

    async def _dm(self, member, title, text, color):
        try:
            await member.send(embed=ui.make(title, text, color=color))
        except discord.HTTPException:
            pass

    async def panel_embed(self, guild: discord.Guild) -> discord.Embed:
        rows = await self.bot.db.fetchall(
            "SELECT * FROM afk WHERE guild_id=? AND kind IN ('afk','inactive') ORDER BY until", guild.id)

        def lines(kind):
            out = []
            for r in rows:
                if r["kind"] == kind:
                    out.append(f"• <@{r['user_id']}> — до {fmt_date(r['until'])} (вернётся через {fmt_left(r['until'])})"
                               + (f"\n  └ {r['reason']}" if r["reason"] and kind == "inactive" else ""))
            return "\n".join(out)[:1500] or "ℹ️ Сейчас никого нет"

        warns = await get_channel(self.bot, guild, "ch_warns")
        warns_text = warns.mention if warns else "канал варнов"
        minutes = config.AFK_WARN_MINUTES
        warn_line = (f"Если вы сидите в голосовом канале с выключенным звуком дольше {minutes} мин. без статуса AFK, "
                     "предупреждение придёт в канал ниже." if minutes > 0 else
                     "Предупреди старший состав, если тебя не будет.")
        desc = (f"**Предупреди старший состав о своём отсутствии.**\n{warn_line}\n\n"
                "**Важно**\n"
                "• AFK добавляется сразу в список.\n"
                "• Инактив отправляется на рассмотрение.\n"
                "• После возвращения нажмите кнопку «Вернулся».\n\n"
                f"-# Предупреждения приходят в {warns_text}\n\n"
                f"### 🌙 AFK\n{lines('afk')}\n"
                f"### 🏖️ Инактив\n{lines('inactive')}")
        return ui.make("⚙️ Инактив-панель", desc, color=PANEL_COLOR)

    async def refresh_panel(self, guild: discord.Guild):
        msg_id = await self.bot.db.get_setting(guild.id, "msg_afk")
        ch = await get_channel(self.bot, guild, "ch_afk")
        if not (msg_id and ch):
            return
        try:
            msg = await ch.fetch_message(msg_id)
            await msg.edit(embed=await self.panel_embed(guild), view=AFKPanelView())
        except discord.HTTPException:
            pass

    async def post_panel(self, channel, key):
        msg = await channel.send(embed=await self.panel_embed(channel.guild), view=AFKPanelView())
        await self.bot.db.set_setting(channel.guild.id, "msg_afk", msg.id)

    # ---------------------------------------------------------------- действия
    async def start_afk(self, interaction: discord.Interaction, minutes: int, reason: str | None, edit: bool = False):
        g, member = interaction.guild, interaction.user

        async def reply(embed):
            if edit:
                await interaction.response.edit_message(content=None, embed=embed, view=None)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)

        if await self.bot.db.fetchone("SELECT 1 FROM afk WHERE guild_id=? AND user_id=?", g.id, member.id):
            return await reply(ui.err("Вы уже в AFK/Инактиве — нажмите «Вернулся»."))
        until = int(time.time()) + minutes * 60
        await self.bot.db.execute("INSERT INTO afk(guild_id,user_id,kind,until,reason) VALUES(?,?,?,?,?)",
                                  g.id, member.id, "afk", until, reason or "")
        await self._role(member, "role_afk", True)
        e = ui.make("🌙 AFK установлен", f"До <t:{until}:f> ({ui.fmt_minutes(minutes)})", color=config.COLOR_INFO)
        if reason:
            e.add_field(name="📝 Причина", value=reason, inline=False)
        await reply(e)
        await send_log(self.bot, g, ui.make("🌙 AFK установлен", f"{member.mention} на **{ui.fmt_minutes(minutes)}**"
                                           + (f"\nПричина: {reason}" if reason else ""), color=config.COLOR_INFO), "ch_log_afk")
        await self.refresh_panel(g)

    async def end_afk(self, guild: discord.Guild, user_id: int, expired: bool = False, by=None) -> bool:
        row = await self.bot.db.fetchone("SELECT kind FROM afk WHERE guild_id=? AND user_id=?", guild.id, user_id)
        if not row:
            return False
        await self.bot.db.execute("DELETE FROM afk WHERE guild_id=? AND user_id=?", guild.id, user_id)
        member = guild.get_member(user_id)
        if member:
            await self._role(member, "role_afk", False)
            await self._role(member, "role_inactive", False)
        how = "время вышло" if expired else (f"снял {by.mention}" if by else "вернулся вручную")
        await send_log(self.bot, guild, ui.make("🚪 Возвращение", f"<@{user_id}> — {how}", color=config.COLOR_OK), "ch_log_afk")
        await self.refresh_panel(guild)
        return True

    async def request_inactive(self, interaction: discord.Interaction, days_raw: str, reason: str):
        g, member = interaction.guild, interaction.user
        if not days_raw.strip().isdigit() or not 1 <= int(days_raw) <= 60:
            return await interaction.response.send_message(embed=ui.err("Укажите число дней от 1 до 60."), ephemeral=True)
        if await self.bot.db.fetchone("SELECT 1 FROM afk WHERE guild_id=? AND user_id=?", g.id, member.id):
            return await interaction.response.send_message(
                embed=ui.err("У вас уже есть AFK/Инактив или заявка на него."), ephemeral=True)
        ch = await get_channel(self.bot, g, "ch_log_afk")
        if not ch:
            return await interaction.response.send_message(embed=ui.err("Канал AFK-логов не настроен (`!setup`)."), ephemeral=True)
        days = int(days_raw)
        until = int(time.time()) + days * 86400
        e = ui.make("🏖️ Запрос на инактив",
                    f"{member.mention} просит инактив на **{days} дн.** (до {fmt_date(until)})",
                    color=config.COLOR_WARN, thumbnail=member.display_avatar.url)
        e.add_field(name="Причина", value=reason, inline=False)
        msg = await ch.send(embed=e, view=InactiveReviewView())
        await self.bot.db.execute("INSERT INTO afk(guild_id,user_id,kind,until,reason,msg_id) VALUES(?,?,?,?,?,?)",
                                  g.id, member.id, "pending", until, reason[:150], msg.id)
        await interaction.response.send_message(embed=ui.ok("Инактив отправлен на рассмотрение."), ephemeral=True)

    # ---------------------------------------------------------------- циклы
    @tasks.loop(seconds=30)
    async def expire(self):
        rows = await self.bot.db.fetchall(
            "SELECT guild_id,user_id FROM afk WHERE kind IN ('afk','inactive') AND until<=?", int(time.time()))
        for r in rows:
            guild = self.bot.get_guild(r["guild_id"])
            if guild:
                await self.end_afk(guild, r["user_id"], expired=True)

    @tasks.loop(seconds=60)
    async def warn_loop(self):
        """Предупреждение в #варны: давно сидит в голосовом с выключенным звуком и без статуса AFK."""
        now = time.time()
        seen = set()
        for guild in self.bot.guilds:
            afk_vc = await self.bot.db.get_setting(guild.id, "vc_afk")
            for vc in guild.voice_channels:
                if vc.id == afk_vc or vc == guild.afk_channel:
                    continue
                for m in vc.members:
                    if m.bot or not m.voice or not (m.voice.self_deaf or m.voice.deaf):
                        continue
                    key = (guild.id, m.id)
                    seen.add(key)
                    self.idle.setdefault(key, (now, vc.id))
        for key in list(self.idle):
            if key not in seen:
                self.idle.pop(key, None)
                self.warned.discard(key)
        for key, (since, vc_id) in list(self.idle.items()):
            if key in self.warned or now - since < config.AFK_WARN_MINUTES * 60:
                continue
            guild = self.bot.get_guild(key[0])
            member = guild.get_member(key[1]) if guild else None
            channel = await get_channel(self.bot, guild, "ch_warns") if guild else None
            if not (member and channel):
                continue
            if await self.bot.db.fetchone("SELECT 1 FROM afk WHERE guild_id=? AND user_id=?", key[0], key[1]):
                continue
            self.warned.add(key)
            e = ui.make("⚠️ Нет статуса AFK",
                        f"{member.mention} уже **{int((now - since) // 60)} мин.** в {guild.get_channel(vc_id).mention} "
                        "с выключенным звуком, но без статуса AFK/Инактив.", color=config.COLOR_WARN,
                        thumbnail=member.display_avatar.url)
            await channel.send(content=member.mention, embed=e)

    @expire.before_loop
    @warn_loop.before_loop
    async def _wait(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(AFK(bot))
