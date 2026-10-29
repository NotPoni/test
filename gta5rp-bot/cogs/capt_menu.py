"""Меню CAPT: одно сообщение-контейнер + ветка для записи.
Участники пишут в ветке, сотрудник ставит ✅ (в состав) или ❌ (исключить). Требуется discord.py >= 2.6."""
import asyncio
import json
import logging
import time
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

import config
import ui
from checks import get_channel, is_staff, level, send_log, staff_only
from utils import parse_when

OK, NO = "✅", "❌"
NUMS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
MAX_BLOCK = 2400  # Components V2: не более 4000 символов текста на всё сообщение
log = logging.getLogger(__name__)


def _json(raw, default):
    try:
        value = json.loads(raw) if raw else default
        return value if isinstance(value, type(default)) else default
    except (TypeError, ValueError):
        return default


def render_blocks(d: dict) -> tuple[str, str, str]:
    """Возвращает (заголовок, блок информации, блок состава)."""
    cats = _json(d.get("categories"), [])
    roster = _json(d.get("roster"), {})
    if d.get("status") == "finished":
        reg = "завершена 🏁"
    else:
        reg = "доступна ✅" if d.get("reg_open") else "закрыта ❌"
    info = f"**Регистрация:** {reg}\n**Время проведения:** `{d.get('time_text') or '—'}`"
    if d.get("thread_id"):
        info += f"\n**Ветка:** <#{d['thread_id']}>"
    info += ("\n\n*Оставьте сообщение в ветке ниже. Администратор отметит его реакцией "
             f"{OK}, и пользователь попадёт в основной состав.*\n"
             f"*Реакция {NO} — исключает из основного состава.*")
    n, blocks, used = 0, [], 0
    for cat in cats:
        lines = []
        for uid in roster.get(cat, []):
            n += 1
            lines.append(f"`{n}.` <@{uid}>")
        block = f"### {cat}\n" + ("\n".join(lines) if lines else "*пока никого*")
        if used + len(block) > MAX_BLOCK:
            blocks.append("-# …состав обрезан, смотрите ветку")
            break
        used += len(block)
        blocks.append(block)
    return f"## {d.get('title') or '—'}", info, "\n\n".join(blocks) or "*пока никого*"


class ToggleButton(discord.ui.Button):
    def __init__(self, reg_open: bool):
        super().__init__(label="Закрыть регистрацию" if reg_open else "Открыть регистрацию",
                         emoji="🔒" if reg_open else "🔓", style=discord.ButtonStyle.secondary,
                         custom_id="capt:toggle")

    async def callback(self, interaction: discord.Interaction):
        await interaction.client.get_cog("CaptMenu").toggle(interaction)


class FinishButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Завершить и начислить баллы", emoji="🏁", style=discord.ButtonStyle.success,
                         custom_id="capt:finish")

    async def callback(self, interaction: discord.Interaction):
        await interaction.client.get_cog("CaptMenu").finish(interaction)


class CaptMenuView(discord.ui.LayoutView):
    def __init__(self, d: dict | None = None):
        super().__init__(timeout=None)
        d = {**dict(d or {})}
        d.setdefault("title", "—")
        d.setdefault("time_text", "—")
        d.setdefault("categories", '["MCL","CAPT"]')
        d.setdefault("roster", "{}")
        d.setdefault("reg_open", 1)
        d.setdefault("status", "open")
        d.setdefault("thread_id", 0)
        title, info, roster = render_blocks(d)
        c = discord.ui.Container(accent_colour=discord.Colour(0xFFFFFF))
        if d.get("ping"):
            c.add_item(discord.ui.TextDisplay("@everyone"))
        c.add_item(discord.ui.TextDisplay(title))
        c.add_item(discord.ui.Separator())
        c.add_item(discord.ui.TextDisplay(info))
        c.add_item(discord.ui.Separator())
        c.add_item(discord.ui.TextDisplay(roster))
        if d["status"] == "open":
            row = discord.ui.ActionRow()
            row.add_item(ToggleButton(bool(d["reg_open"])))
            row.add_item(FinishButton())
            c.add_item(row)
        self.add_item(c)


class CaptMenu(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()

    async def cog_load(self):
        self.bot.add_view(CaptMenuView())

    # ---------------------------------------------------------------- создание
    @app_commands.command(name="capt", description="Создать меню CAPT с веткой для записи")
    @app_commands.describe(title="Название, например: ЗА ОСОБУ vs hated", start_time="Время: 18:20 или 25.12 21:30",
                           categories="Списки через запятую (по умолчанию MCL,CAPT)",
                           ping="Пинговать @everyone")
    @app_commands.guild_only()
    @staff_only()
    async def capt(self, interaction: discord.Interaction, title: str, start_time: str,
                   categories: str = "MCL,CAPT", ping: bool = True):
        when = parse_when(start_time)
        if not when:
            return await interaction.response.send_message(
                embed=ui.err("Неверное время. Примеры: `18:20`, `25.12 21:30`."), ephemeral=True)
        cats = [c.strip()[:30] for c in categories.split(",") if c.strip()][:9]
        if not cats:
            return await interaction.response.send_message(embed=ui.err("Укажите хотя бы один список."), ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        g = interaction.guild
        channel = await get_channel(self.bot, g, "ch_capt") or interaction.channel
        if not isinstance(channel, discord.TextChannel):
            return await interaction.followup.send(embed=ui.err("Канал для CAPT не найден."), ephemeral=True)
        now = datetime.now(config.TZ)
        time_text = when.strftime("%H:%M") if when.date() == now.date() else when.strftime("%d.%m %H:%M")
        d = dict(guild_id=g.id, channel_id=channel.id, thread_id=0, title=title, time_text=time_text,
                 categories=json.dumps(cats, ensure_ascii=False), roster="{}", reg_open=1, status="open",
                 author_id=interaction.user.id, ping=int(ping), message_id=0)
        try:
            msg = await channel.send(view=CaptMenuView(d),
                                     allowed_mentions=discord.AllowedMentions(everyone=True, users=False, roles=False))
        except discord.HTTPException:
            return await interaction.followup.send(embed=ui.err("Не удалось отправить меню в канал."), ephemeral=True)
        d["message_id"] = msg.id
        try:
            thread = await msg.create_thread(name=f"{title} • запись"[:100], auto_archive_duration=10080)
        except discord.HTTPException:
            try:
                thread = await channel.create_thread(name=f"{title} • запись"[:100],
                                                     type=discord.ChannelType.public_thread, auto_archive_duration=10080)
            except discord.HTTPException:
                thread = None
        if thread is None:
            try:
                await msg.delete()
            except discord.HTTPException:
                pass
            return await interaction.followup.send(embed=ui.err("Не удалось создать ветку записи."), ephemeral=True)
        d["thread_id"] = thread.id
        await self.bot.db.execute(
            "INSERT INTO capt_menus(message_id,guild_id,channel_id,thread_id,title,time_text,categories,author_id) "
            "VALUES(?,?,?,?,?,?,?,?)", msg.id, g.id, channel.id, thread.id, title, time_text, d["categories"],
            interaction.user.id)
        try:
            await msg.edit(view=CaptMenuView(d), allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass
        try:
            await thread.send("📝 **Запись открыта.** Напишите здесь сообщение"
                              + (f" (укажите: {', '.join(cats)})" if len(cats) > 1 else "") + ".")
        except discord.HTTPException:
            pass
        await interaction.followup.send(embed=ui.ok(f"Меню создано: {msg.jump_url}"), ephemeral=True)

    # ---------------------------------------------------------------- обновление
    async def _row(self, **where):
        key, value = next(iter(where.items()))
        return await self.bot.db.fetchone(f"SELECT * FROM capt_menus WHERE {key}=?", value)

    async def refresh(self, guild: discord.Guild, d: dict):
        d = dict(d)
        ch = guild.get_channel(d.get("channel_id") or 0)
        if not isinstance(ch, discord.TextChannel) or not d.get("message_id"):
            return
        try:
            msg = await ch.fetch_message(d["message_id"])
            await msg.edit(view=CaptMenuView(d), allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

    async def _lock_thread(self, guild, d, locked: bool):
        if not d.get("thread_id"):
            return
        try:
            th = guild.get_thread(d["thread_id"]) or await guild.fetch_channel(d["thread_id"])
            await th.edit(locked=locked)
        except discord.HTTPException:
            pass

    # ---------------------------------------------------------------- реакции
    @staticmethod
    def _detect(cats: list[str], text: str) -> str:
        low = (text or "").lower()
        for c in cats:
            if c.lower() in low:
                return c
        return cats[-1]

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if not payload.guild_id or payload.user_id == self.bot.user.id:
            return
        emoji = str(payload.emoji)
        if emoji not in (OK, NO) and emoji not in NUMS:
            return
        try:
            row = await self.bot.db.fetchone(
                "SELECT * FROM capt_menus WHERE thread_id=? AND status='open'", payload.channel_id)
            if not row:
                return
            guild = self.bot.get_guild(payload.guild_id)
            if guild is None:
                return
            member = payload.member or guild.get_member(payload.user_id)
            if not member or await level(self.bot, member) < 1:
                return
            try:
                th = guild.get_thread(payload.channel_id) or await guild.fetch_channel(payload.channel_id)
                msg = await th.fetch_message(payload.message_id)
            except discord.HTTPException:
                return
            if msg.author.bot:
                return
            async with self.lock:
                fresh = await self._row(message_id=row["message_id"])
                if not fresh or fresh["status"] != "open":
                    return
                d = dict(fresh)
                cats = _json(d.get("categories"), [])
                roster = _json(d.get("roster"), {})
                uid = msg.author.id
                for lst in roster.values():
                    if uid in lst:
                        lst.remove(uid)
                if emoji != NO:
                    if sum(len(v) for v in roster.values()) >= config.EVENT_MAX_TOTAL:
                        return await th.send(embed=ui.err("Состав заполнен."), delete_after=10)
                    if emoji in NUMS:
                        idx = NUMS.index(emoji)
                        cat = cats[idx] if idx < len(cats) else cats[-1]
                    else:
                        cat = self._detect(cats, msg.content)
                    roster.setdefault(cat, []).append(uid)
                d["roster"] = json.dumps(roster)
                await self.bot.db.execute("UPDATE capt_menus SET roster=? WHERE message_id=?",
                                          d["roster"], d["message_id"])
            await self.refresh(guild, d)
        except Exception:
            log.exception("Ошибка обработки реакции CAPT")

    # ---------------------------------------------------------------- кнопки
    async def toggle(self, interaction: discord.Interaction):
        if not await is_staff(interaction):
            return await interaction.response.send_message(embed=ui.err("Недостаточно прав."), ephemeral=True)
        row = await self._row(message_id=interaction.message.id)
        if not row:
            return await interaction.response.send_message(embed=ui.err("Меню не найдено в базе."), ephemeral=True)
        if row["status"] != "open":
            return await interaction.response.send_message(embed=ui.err("CAPT уже завершён."), ephemeral=True)
        current = 1 if row["reg_open"] else 0
        new = 0 if current else 1
        cur = await self.bot.db.execute(
            "UPDATE capt_menus SET reg_open=? WHERE message_id=? AND status='open' AND reg_open=?",
            new, row["message_id"], current)
        if cur.rowcount == 0:
            return await interaction.response.send_message(embed=ui.err("Статус уже изменили."), ephemeral=True)
        d = dict(row)
        d["reg_open"] = new
        try:
            await interaction.response.edit_message(view=CaptMenuView(d),
                                                    allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass
        await self._lock_thread(interaction.guild, d, locked=not new)
        await self.refresh(interaction.guild, d)

    async def finish(self, interaction: discord.Interaction):
        if not await is_staff(interaction):
            return await interaction.response.send_message(embed=ui.err("Недостаточно прав."), ephemeral=True)
        row = await self._row(message_id=interaction.message.id)
        if not row:
            return await interaction.response.send_message(embed=ui.err("Меню не найдено в базе."), ephemeral=True)
        if row["status"] != "open":
            return await interaction.response.send_message(embed=ui.err("Уже завершено."), ephemeral=True)
        await interaction.response.defer()
        cur = await self.bot.db.execute(
            "UPDATE capt_menus SET status='finished' WHERE message_id=? AND status='open'", row["message_id"])
        if cur.rowcount == 0:
            return await interaction.followup.send(embed=ui.err("Уже завершено."), ephemeral=True)
        d = dict(row)
        g = interaction.guild
        players = [u for lst in _json(d.get("roster"), {}).values() for u in lst]
        reward = config.REWARDS["capt"]
        d["status"] = "finished"
        points = self.bot.get_cog("Points")
        for uid in players:
            if points and reward:
                await points.add_points(g.id, uid, reward, interaction.user.id, "CAPT", f"{d['title']}")
            await self.bot.db.execute("INSERT INTO events_log(guild_id,user_id,kind,ts) VALUES(?,?,?,?)",
                                      g.id, uid, "capt", int(time.time()))
        if interaction.message is not None:
            try:
                await interaction.message.edit(view=CaptMenuView(d), allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass
        await self._lock_thread(g, d, locked=True)
        log_embed = ui.make(f"🏁 CAPT завершён: {d['title']}",
                            f"Завершил {interaction.user.mention}\nВ составе: **{len(players)}**\n"
                            f"Награда: **{reward:g}** баллов каждому\n"
                            f"[К меню]({interaction.message.jump_url if interaction.message else '—'})",
                            color=config.COLOR_OK)
        await send_log(self.bot, g, log_embed, "ch_log_capt")
        await interaction.followup.send(
            embed=ui.ok(f"Начислено **{reward:g}** баллов {len(players)} участникам."), ephemeral=True)


async def setup(bot):
    await bot.add_cog(CaptMenu(bot))
