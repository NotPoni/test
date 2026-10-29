"""Заявки: две формы (RP+CAPT и RP), канал заявка-N,
«Взять на рассмотрение» → Принять / Отклонить / Обзвон / Обновить / Закрыть.

Важно: канал заявки удаляется с задержкой, иначе ответ на interaction
(followup) уходил бы в уже удалённый канал и падал с 404 Unknown Channel.
"""
import asyncio
import html
import io
import json
import time
from datetime import datetime

import discord
from discord.ext import commands

import config
import texts
import ui
from checks import get_channel, get_role, is_staff, send_log, staff_roles

FIELDS = {
    "RP+CAPT": [
        ("Ваш статический ID & Nickname", "Пример: #777 / Ayato Enemy", True, 100),
        ("Имя & Возраст (IRL)", "Имя: [Ваше имя] / Возраст: 15+", True, 100),
        ("Часы в GTA 5 / Среднесуточный онлайн", "Пример: 1к часов / 5 часов в день", True, 100),
        ("Перечислите свои предыдущие семьи", "Семьи: [Ваши семьи] / Причины: [Причины ухода]", True, 500),
        ("Откаты GG (тяж/спеш) / Видеохостинг", "Откаты: 5 мин (16-18)\nВидеохостинг: YouTube, RuTube и др.", True, 500),
    ],
    "RP": [
        ("Ваш статический ID & Nickname", "Пример: #777 / Ayato Enemy", True, 100),
        ("Ваше имя", "Ваше реальное имя", True, 50),
        ("Возраст", "Ваш возраст", True, 20),
    ],
}
MAPPING = {
    "RP+CAPT": {
        "Ваш статический ID & Nickname": "🆔 Статик ID & Nickname",
        "Имя & Возраст (IRL)": "👤 Имя & Возраст",
        "Часы в GTA 5 / Среднесуточный онлайн": "⏰ Часы в GTA / Онлайн",
        "Перечислите свои предыдущие семьи": "🏠 Предыдущие семьи",
        "Откаты GG (тяж/спеш) / Видеохостинг": "🔫 Откаты GG / Видеохостинг",
    },
    "RP": {
        "Ваш статический ID & Nickname": "🆔 Статик ID & Nickname",
        "Ваше имя": "👤 Ваше имя",
        "Возраст": "📅 Возраст",
    },
}
ACTIVE_STATUSES = ("pending", "review")
ACTIVE = "('pending','review')"
GREY, YELLOW, GREEN, RED = 0x2B2D31, 0xFFFF00, 0x00FF00, 0xFF0000

_bg_tasks: set[asyncio.Task] = set()


def _spawn(coro):
    """Фоновая задача с удержанием ссылки, чтобы её не собрал GC."""
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


async def _delete_later(channel: discord.abc.GuildChannel, delay: float = 3.0):
    await asyncio.sleep(delay)
    try:
        await channel.delete(reason="Заявка обработана")
    except discord.HTTPException:
        pass


async def reply(interaction: discord.Interaction, embed: discord.Embed):
    """Эфемерный ответ, который не падает при повторном/устаревшем ответе."""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.HTTPException:
        pass


def icon_for(guild: discord.Guild):
    return config.LOGO_URL or (guild.icon.url if guild.icon else None)


def build_embed(guild: discord.Guild, row, status: str) -> discord.Embed:
    try:
        data = json.loads(row["data"] or "{}")
    except (TypeError, ValueError):
        data = {}
    mapping = MAPPING.get(row["kind"], {})
    e = ui.make(f"📋 Заявка #{row['id']}", color=YELLOW if status == "review" else GREY)
    e.set_author(name=config.FAMILY_NAME, icon_url=icon_for(guild))
    for key, value in data.items():
        if value and value.strip():
            e.add_field(name=mapping.get(key, key), value=f"```{ui.cut(value, 1000)}```", inline=False)
    e.add_field(name="👤 Пользователь", value=f"<@{row['user_id']}>", inline=True)
    e.add_field(name="🆔 ID", value=str(row["user_id"]), inline=True)
    e.add_field(name="📌 Тип заявки", value=row["kind"], inline=True)
    e.add_field(name="📌 Статус", value="🟡 На рассмотрении" if status == "review" else "📋 Ожидает", inline=False)
    e.set_footer(text=f"ID: {row['id']} • {datetime.now(config.TZ):%d.%m.%Y %H:%M}", icon_url=icon_for(guild))
    return e


async def transcript_html(channel: discord.TextChannel, app_id: int) -> discord.File:
    """Транскрипт заявки. Включает embed'ы — в них лежат ответы анкеты."""
    rows = []
    try:
        async for m in channel.history(limit=1000, oldest_first=True):
            body = []
            if m.content:
                body.append(html.escape(m.content).replace("\n", "<br>"))
            for e in m.embeds:
                if e.title:
                    body.append(f'<div class="embed-title">{html.escape(e.title)}</div>')
                if e.description:
                    body.append(f'<div class="embed">{html.escape(e.description)}</div>')
                for f in e.fields:
                    body.append(f'<div class="field"><b>{html.escape(f.name)}</b>'
                                f"<pre>{html.escape(f.value)}</pre></div>")
            for a in m.attachments:
                body.append(f'<a href="{html.escape(a.url)}">{html.escape(a.filename)}</a>')
            if not body and m.author.bot:
                continue
            rows.append(
                f'<div class="msg"><span class="time">{m.created_at:%d.%m.%Y %H:%M}</span> '
                f'<span class="author">{html.escape(m.author.display_name)}</span>: '
                f'<span class="content">{"".join(body) or "Вложение"}</span></div>')
    except discord.HTTPException:
        rows.append('<p style="color:#e74c3c;">Не удалось прочитать историю канала.</p>')
    body = "".join(rows) or '<p style="color:#888;">Нет сообщений в этом тикете.</p>'
    css = ("body{font-family:Arial,sans-serif;background:#1a1a2e;color:#eee;padding:20px}"
           ".header{background:#16213e;padding:15px;border-radius:10px;margin-bottom:20px}"
           ".msg{padding:8px 12px;margin:4px 0;background:#2a2a4a;border-radius:6px}"
           ".time{color:#888;font-size:12px}.author{color:#4fc3f7;font-weight:bold}"
           ".embed-title{color:#f1c40f;font-weight:bold;margin-top:6px}"
           ".embed{color:#ddd;margin-top:4px}.field{margin-top:4px}"
           ".field pre{white-space:pre-wrap;margin:2px 0;color:#eee}"
           ".footer{margin-top:20px;text-align:center;color:#666;font-size:12px}")
    doc = (f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Транскрипт заявки #{app_id}</title>'
           f"<style>{css}</style></head><body><div class=\"header\"><h2>📋 Транскрипт заявки #{app_id}</h2>"
           f"<p>Канал: #{html.escape(channel.name)} • {datetime.now(config.TZ):%d.%m.%Y %H:%M}</p>"
           f"<p>Всего сообщений: {len(rows)}</p></div>{body}"
           '<div class="footer">Транскрипт сгенерирован автоматически</div></body></html>')
    return discord.File(io.BytesIO(doc.encode("utf-8")), filename=f"application_{app_id}.html")


async def get_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except discord.HTTPException:
            member = None
    return member


async def finish(interaction: discord.Interaction, row, status: str, title: str, color: int,
                 note: str | None = None, *, delete: bool = True, delay: float = 3.0) -> bool:
    """Общий финал: статус в БД, снять «Подал заявку», транскрипт в лог, удалить канал.

    Возвращает False, если заявку уже обработали (двойной клик / устаревшая кнопка).
    """
    bot, g, db = interaction.client, interaction.guild, interaction.client.db
    cur = await db.execute(
        "UPDATE apps SET status=?, reviewer_id=? WHERE id=? AND status IN ('pending','review')",
        status, interaction.user.id, row["id"])
    if cur.rowcount == 0:
        return False

    member = await get_member(g, row["user_id"])
    applicant = await get_role(bot, g, "role_applicant")
    if member and applicant and applicant in member.roles:
        try:
            await member.remove_roles(applicant, reason=f"Заявка #{row['id']}")
        except discord.HTTPException:
            pass

    channel = g.get_channel(row["channel_id"])
    log = ui.make(f"{title} • #{row['id']}",
                  f"<@{row['user_id']}> → {interaction.user.mention}" + (f"\n**Причина:** {note}" if note else ""),
                  color=color)
    logch = await get_channel(bot, g, "ch_log_apps")
    if logch:
        try:
            file = await transcript_html(channel, row["id"]) if channel else None
            await logch.send(embed=log, file=file)
        except discord.HTTPException:
            try:
                await logch.send(embed=log)
            except discord.HTTPException:
                pass

    if channel and delete:
        _spawn(_delete_later(channel, delay))
    return True


async def dm_result(bot, user_id: int, text: str, color: int, handler, reason: str | None = None):
    try:
        user = await bot.fetch_user(user_id)
        e = ui.make("📋 Результат заявки", text, color=color)
        e.add_field(name="Обработал", value=handler.mention)
        if reason:
            e.add_field(name="Причина", value=ui.cut(reason, 1024), inline=False)
        await user.send(embed=e)
    except discord.HTTPException:
        pass


# ------------------------------------------------------------------ подача
class ApplyModal(discord.ui.Modal):
    def __init__(self, kind: str):
        super().__init__(title=f"📝 Подача заявки {kind}")
        self.kind = kind
        for label, placeholder, required, max_len in FIELDS[kind]:
            self.add_item(discord.ui.TextInput(
                label=label[:45], placeholder=placeholder, required=required, max_length=max_len,
                style=discord.TextStyle.paragraph if max_len > 100 else discord.TextStyle.short))

    async def on_submit(self, interaction: discord.Interaction):
        bot, g, db = interaction.client, interaction.guild, interaction.client.db
        if g is None:
            return await reply(interaction, ui.err("Заявки подаются только на сервере."))
        active = await db.fetchone(
            f"SELECT channel_id FROM apps WHERE guild_id=? AND user_id=? AND status IN {ACTIVE}",
            g.id, interaction.user.id)
        if active and g.get_channel(active["channel_id"]):
            return await reply(interaction, ui.err(f"У вас уже есть активная заявка: <#{active['channel_id']}>"))
        if active:
            # канал старой заявки удалили вручную — закрываем «зависшую» запись
            await db.execute("UPDATE apps SET status='closed' WHERE guild_id=? AND user_id=? AND status IN " + ACTIVE,
                             g.id, interaction.user.id)
        await interaction.response.defer(ephemeral=True)

        data = {c.label: c.value for c in self.children}
        cur = await db.execute("INSERT INTO apps(guild_id,user_id,kind,data,created) VALUES(?,?,?,?,?)",
                               g.id, interaction.user.id, self.kind,
                               json.dumps(data, ensure_ascii=False), int(time.time()))
        app_id = cur.lastrowid

        category = await get_channel(bot, g, "cat_tickets")
        if not isinstance(category, discord.CategoryChannel):
            category = discord.utils.get(g.categories, name=config.TICKETS_CATEGORY_NAME)
        if category is None:
            try:
                category = await g.create_category(
                    config.TICKETS_CATEGORY_NAME,
                    overwrites={g.default_role: discord.PermissionOverwrite(view_channel=False)})
                await db.set_setting(g.id, "cat_tickets", category.id)
            except discord.HTTPException:
                category = None

        perms = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                            attach_files=True, embed_links=True)
        overwrites = {g.default_role: discord.PermissionOverwrite(view_channel=False),
                      interaction.user: perms,
                      g.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)}
        for role in await staff_roles(bot, g):
            overwrites[role] = perms
        try:
            channel = await g.create_text_channel(f"заявка-{app_id}", category=category, overwrites=overwrites,
                                                  topic=f"app:{app_id}:{interaction.user.id}")
        except discord.HTTPException:
            await db.execute("UPDATE apps SET status='error' WHERE id=?", app_id)
            return await reply(interaction, ui.err("Не удалось создать канал заявки. Сообщите руководству."))
        await db.execute("UPDATE apps SET channel_id=? WHERE id=?", channel.id, app_id)

        applicant = await get_role(bot, g, "role_applicant")
        if applicant:
            try:
                await interaction.user.add_roles(applicant, reason=f"Заявка #{app_id}")
            except discord.HTTPException:
                pass

        row = await db.fetchone("SELECT * FROM apps WHERE id=?", app_id)
        pings = []
        for key in ("role_high", "role_recruiter"):
            r = await get_role(bot, g, key)
            if r and r.mention not in pings:
                pings.append(r.mention)
        try:
            await channel.send(content=" ".join(pings) or None, embed=build_embed(g, row, "pending"),
                               view=ReviewView("new"), allowed_mentions=discord.AllowedMentions(roles=True))
        except discord.HTTPException:
            pass

        await send_log(bot, g, ui.make(f"📝 Создана заявка {self.kind}",
                                       f"{interaction.user.mention} создал заявку #{app_id} ({self.kind}) • {channel.mention}",
                                       color=config.COLOR_INFO), "ch_log_apps")
        try:
            dm = ui.make("✅ Заявка подана!", f"Ваша {self.kind} заявка #{app_id} успешно создана.", color=GREEN)
            dm.add_field(name="Канал", value=channel.mention, inline=False)
            await interaction.user.send(embed=dm)
        except discord.HTTPException:
            pass
        await reply(interaction, ui.ok(f"✅ Заявка #{app_id} ({self.kind}) создана! Канал: {channel.mention}"))


class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📝 Подать заявку RP+CAPT", style=discord.ButtonStyle.primary, custom_id="app:full")
    async def full(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ApplyModal("RP+CAPT"))

    @discord.ui.button(label="📝 Подать заявку RP", style=discord.ButtonStyle.secondary, custom_id="app:simple")
    async def simple(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ApplyModal("RP"))


# ------------------------------------------------------------------ рассмотрение
class DenyModal(discord.ui.Modal, title="Причина отклонения"):
    reason = discord.ui.TextInput(label="Причина отклонения", placeholder="Укажите причину...",
                                  style=discord.TextStyle.paragraph, required=True, max_length=500)

    def __init__(self, row):
        super().__init__()
        self.row = row

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await dm_result(interaction.client, self.row["user_id"], "Ваша заявка была **отклонена ❌**!", RED,
                        interaction.user, self.reason.value)
        if not await finish(interaction, self.row, "denied", "❌ Заявка отклонена", RED, self.reason.value):
            return await reply(interaction, ui.err("Заявка уже обработана."))
        await reply(interaction, ui.ok("✅ Заявка отклонена."))


class CallSelect(discord.ui.Select):
    def __init__(self, row, channels):
        super().__init__(placeholder="Выберите канал для обзвона",
                         options=[discord.SelectOption(label=f"🔊 {c.name}"[:100], value=str(c.id)) for c in channels[:25]])
        self.row = row

    async def callback(self, interaction: discord.Interaction):
        g = interaction.guild
        vc = g.get_channel(int(self.values[0]))
        member = g.get_member(self.row["user_id"])
        if not member or not vc:
            return await interaction.response.edit_message(content="❌ Пользователь или канал не найден.", view=None)
        if member.voice and member.voice.channel:
            try:
                await member.move_to(vc)
                return await interaction.response.edit_message(content=f"✅ {member.mention} вызван в {vc.mention}", view=None)
            except discord.HTTPException:
                pass  # не смогли переместить — пригласим текстом
        e = ui.make("🔊 Вас вызывают на обзвон!",
                    f"{member.mention}, вас вызывают на обзвон!\nЗайдите в голосовой канал.", color=0x5865F2)
        e.add_field(name="Заявка", value=f"#{self.row['id']}")
        e.add_field(name="Рекрутер", value=interaction.user.mention)
        e.add_field(name="Канал", value=vc.mention)
        ticket = g.get_channel(self.row["channel_id"])
        if ticket:
            try:
                await ticket.send(content=member.mention, embed=e)
            except discord.HTTPException:
                pass
        try:
            await member.send(embed=e)
        except discord.HTTPException:
            pass
        await interaction.response.edit_message(content=f"✅ {member.mention} вызван!", view=None)


class CloseView(discord.ui.View):
    """Выбор действия при закрытии (видно только нажавшему)."""

    def __init__(self, row):
        super().__init__(timeout=300)
        self.row = row

    @discord.ui.button(label="📄 Создать транскрипт", style=discord.ButtonStyle.primary)
    async def transcript(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        ch = interaction.guild.get_channel(self.row["channel_id"])
        if not ch:
            return await reply(interaction, ui.err("Канал не найден."))
        try:
            await interaction.followup.send(embed=ui.make("📄 Транскрипт создан", "Файл во вложении."),
                                            file=await transcript_html(ch, self.row["id"]), ephemeral=True)
        except discord.HTTPException:
            pass

    @discord.ui.button(label="🔒 Закрыть", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if not await finish(interaction, self.row, "closed", "🔒 Закрыта заявка", RED):
            return await reply(interaction, ui.err("Заявка уже обработана."))
        await reply(interaction, ui.ok("✅ Тикет закрыт!"))

    @discord.ui.button(label="🗑️ Удалить канал", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if not await finish(interaction, self.row, "deleted", "🗑️ Канал заявки удалён", RED):
            return await reply(interaction, ui.err("Заявка уже обработана."))
        await reply(interaction, ui.ok("🗑️ Канал удалён!"))


class ReviewView(discord.ui.View):
    def __init__(self, stage: str = "all"):
        super().__init__(timeout=None)
        if stage == "new":
            for b in (self.accept, self.deny, self.call, self.refresh, self.close):
                self.remove_item(b)
        elif stage == "review":
            self.remove_item(self.take)

    async def _guard(self, interaction: discord.Interaction):
        if not await is_staff(interaction):
            await reply(interaction, ui.err("Недостаточно прав."))
            return None
        row = await interaction.client.db.fetchone("SELECT * FROM apps WHERE channel_id=?", interaction.channel.id)
        if not row:
            await reply(interaction, ui.err("Заявка не найдена."))
            return None
        if row["status"] not in ACTIVE_STATUSES:
            await reply(interaction, ui.err("Заявка уже обработана."))
            return None
        return row

    @discord.ui.button(label="📝 Взять на рассмотрение", style=discord.ButtonStyle.primary, custom_id="app:take")
    async def take(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await self._guard(interaction)
        if not row:
            return
        cur = await interaction.client.db.execute(
            "UPDATE apps SET status='review', reviewer_id=? WHERE id=? AND status IN ('pending','review')",
            interaction.user.id, row["id"])
        if cur.rowcount == 0:
            return await reply(interaction, ui.err("Заявка уже обработана."))
        row = dict(row)
        row["status"] = "review"
        await interaction.response.edit_message(embed=build_embed(interaction.guild, row, "review"),
                                                view=ReviewView("review"))
        note = ui.make(f"🟡 Заявка #{row['id']}", f"Заявка взята на рассмотрение {interaction.user.mention}", color=YELLOW)
        note.add_field(name="Статус", value="🟡 На рассмотрении", inline=False)
        try:
            await interaction.channel.send(embed=note)
        except discord.HTTPException:
            pass
        await send_log(interaction.client, interaction.guild,
                       ui.make("🟡 Заявка на рассмотрении", f"Заявка #{row['id']} взята {interaction.user.mention}",
                               color=YELLOW), "ch_log_apps")

    @discord.ui.button(label="✅ Принять", style=discord.ButtonStyle.success, custom_id="app:accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await self._guard(interaction)
        if not row:
            return
        await interaction.response.defer(ephemeral=True)
        bot, g = interaction.client, interaction.guild
        member = await get_member(g, row["user_id"])
        if member:
            add = [r for key in ("role_family", "role_newbie") if (r := await get_role(bot, g, key))]
            try:
                if add:
                    await member.add_roles(*add, reason=f"Заявка #{row['id']} принята")
            except discord.HTTPException:
                await reply(interaction, ui.err("⚠️ Не удалось выдать роли — поднимите роль бота выше."))
        points = bot.get_cog("Points")
        if points:
            await points.add_points(g.id, row["user_id"], 1.0, interaction.user.id, "TICKET", f"Заявка #{row['id']} принята")
        await dm_result(bot, row["user_id"], "Ваша заявка была **принята ✅**! Добро пожаловать в семью.", GREEN, interaction.user)
        if not await finish(interaction, row, "accepted", "✅ Заявка принята", GREEN):
            return await reply(interaction, ui.err("Заявка уже обработана."))
        await reply(interaction, ui.ok("✅ Заявка принята!"))

    @discord.ui.button(label="❌ Отклонить", style=discord.ButtonStyle.danger, custom_id="app:deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await self._guard(interaction)
        if row:
            await interaction.response.send_modal(DenyModal(row))

    @discord.ui.button(label="🔊 Обзвон", style=discord.ButtonStyle.primary, custom_id="app:call")
    async def call(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await self._guard(interaction)
        if not row:
            return
        found = await interaction.client.db.settings_like(interaction.guild_id, "vc_call_")
        channels = [c for cid in found.values() if (c := interaction.guild.get_channel(cid))]
        if not channels:
            return await reply(interaction, ui.err("❌ Нет доступных голосовых каналов."))
        view = discord.ui.View(timeout=60)
        view.add_item(CallSelect(row, channels))
        await interaction.response.send_message("Выберите канал:", view=view, ephemeral=True)

    @discord.ui.button(label="🔄 Обновить", style=discord.ButtonStyle.secondary, custom_id="app:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await self._guard(interaction)
        if row:
            await interaction.response.edit_message(embed=build_embed(interaction.guild, row, row["status"]))

    @discord.ui.button(label="🔒 Закрыть", style=discord.ButtonStyle.danger, custom_id="app:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await self._guard(interaction)
        if row:
            await interaction.response.send_message("Выберите действие:", view=CloseView(row), ephemeral=True)


class Applications(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(PanelView())
        self.bot.add_view(ReviewView())

    async def post_panel(self, channel, key):
        g = channel.guild
        e = ui.make("📋 Подача заявки в семью", texts.APPLY_INFO, color=GREY, banner=True)
        e.set_author(name=config.FAMILY_NAME, icon_url=icon_for(g))
        e.set_footer(text=f"Нажмите на кнопку ниже • {datetime.now(config.TZ):%d.%m.%Y %H:%M}", icon_url=icon_for(g))
        fam = await get_role(self.bot, g, "role_family")
        fam_text = fam.mention if fam else f"**{config.FAMILY_NAME}**"
        e.add_field(name="📌 Типы заявок",
                    value=f"• **RP+CAPT** — полная анкета для вступления в семью {fam_text}\n"
                          "• **RP** — упрощённая анкета (статик, имя, возраст)", inline=False)
        await channel.send(embed=e, view=PanelView())


async def setup(bot):
    await bot.add_cog(Applications(bot))
