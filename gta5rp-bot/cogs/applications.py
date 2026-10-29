"""Заявки — по образцу вашего bot_1.py: две формы (RP+CAPT и RP), канал заявка-N,
«Взять на рассмотрение» → Принять / Отклонить / Обзвон / Обновить / Закрыть."""
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
ACTIVE = "('pending','review')"
GREY, YELLOW, GREEN, RED = 0x2B2D31, 0xFFFF00, 0x00FF00, 0xFF0000


def icon_for(guild: discord.Guild):
    return config.LOGO_URL or (guild.icon.url if guild.icon else None)


def build_embed(guild: discord.Guild, row, status: str) -> discord.Embed:
    data = json.loads(row["data"])
    mapping = MAPPING.get(row["kind"], {})
    e = ui.make(f"📋 Заявка #{row['id']}", color=YELLOW if status == "review" else GREY)
    e.set_author(name=config.FAMILY_NAME, icon_url=icon_for(guild))
    for key, value in data.items():
        if value and value.strip():
            e.add_field(name=mapping.get(key, key), value=f"```{value}```", inline=False)
    e.add_field(name="👤 Пользователь", value=f"<@{row['user_id']}>", inline=True)
    e.add_field(name="🆔 ID", value=str(row["user_id"]), inline=True)
    e.add_field(name="📌 Тип заявки", value=row["kind"], inline=True)
    e.add_field(name="📌 Статус", value="🟡 На рассмотрении" if status == "review" else "📋 Ожидает", inline=False)
    e.set_footer(text=f"ID: {row['id']} • {datetime.now(config.TZ):%d.%m.%Y %H:%M}", icon_url=icon_for(guild))
    return e


async def transcript_html(channel: discord.TextChannel, app_id: int) -> discord.File:
    rows = []
    async for m in channel.history(limit=500, oldest_first=True):
        if m.author.bot:
            continue
        rows.append(
            f'<div class="msg"><span class="time">{m.created_at:%d.%m.%Y %H:%M}</span> '
            f'<span class="author">{html.escape(m.author.display_name)}</span>: '
            f'<span class="content">{html.escape(m.content or "Вложение")}</span></div>')
    body = "".join(rows) or '<p style="color:#888;">Нет сообщений в этом тикете.</p>'
    css = ("body{font-family:Arial,sans-serif;background:#1a1a2e;color:#eee;padding:20px}"
           ".header{background:#16213e;padding:15px;border-radius:10px;margin-bottom:20px}"
           ".msg{padding:8px 12px;margin:4px 0;background:#2a2a4a;border-radius:6px}"
           ".time{color:#888;font-size:12px}.author{color:#4fc3f7;font-weight:bold}"
           ".footer{margin-top:20px;text-align:center;color:#666;font-size:12px}")
    doc = (f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Транскрипт заявки #{app_id}</title>'
           f"<style>{css}</style></head><body><div class=\"header\"><h2>📋 Транскрипт заявки #{app_id}</h2>"
           f"<p>Канал: #{html.escape(channel.name)} • {datetime.now(config.TZ):%d.%m.%Y %H:%M}</p>"
           f"<p>Всего сообщений: {len(rows)}</p></div>{body}"
           '<div class="footer">Транскрипт сгенерирован автоматически</div></body></html>')
    return discord.File(io.BytesIO(doc.encode("utf-8")), filename=f"transcript_ticket_{app_id}.html")


async def finish(interaction: discord.Interaction, row, status: str, title: str, color: int, note: str | None = None):
    """Общий финал: статус в БД, снять «Подал заявку», транскрипт в лог, удалить канал."""
    bot, g, db = interaction.client, interaction.guild, interaction.client.db
    await db.execute("UPDATE apps SET status=?, reviewer_id=? WHERE id=?", status, interaction.user.id, row["id"])
    member = g.get_member(row["user_id"])
    applicant = await get_role(bot, g, "role_applicant")
    if member and applicant:
        try:
            await member.remove_roles(applicant)
        except discord.Forbidden:
            pass
    channel = g.get_channel(row["channel_id"])
    log = ui.make(f"{title} • #{row['id']}", f"<@{row['user_id']}> → {interaction.user.mention}"
                  + (f"\n**Причина:** {note}" if note else ""), color=color)
    logch = await get_channel(bot, g, "ch_log_apps")
    if channel:
        if logch:
            await logch.send(embed=log, file=await transcript_html(channel, row["id"]))
        await channel.delete(reason=f"Заявка #{row['id']}: {status}")
    elif logch:
        await logch.send(embed=log)


async def dm_result(bot, user_id: int, text: str, color: int, handler, reason: str | None = None):
    try:
        user = await bot.fetch_user(user_id)
        e = ui.make("📋 Результат заявки", text, color=color)
        e.add_field(name="Обработал", value=handler.mention)
        if reason:
            e.add_field(name="Причина", value=reason, inline=False)
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
        active = await db.fetchone(
            f"SELECT channel_id FROM apps WHERE guild_id=? AND user_id=? AND status IN {ACTIVE}",
            g.id, interaction.user.id)
        if active and g.get_channel(active["channel_id"]):
            return await interaction.response.send_message(
                embed=ui.err(f"У вас уже есть активная заявка: <#{active['channel_id']}>"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        data = {c.label: c.value for c in self.children}
        cur = await db.execute("INSERT INTO apps(guild_id,user_id,kind,data,created) VALUES(?,?,?,?,?)",
                               g.id, interaction.user.id, self.kind, json.dumps(data, ensure_ascii=False), int(time.time()))
        app_id = cur.lastrowid

        category = await get_channel(bot, g, "cat_tickets")
        if not isinstance(category, discord.CategoryChannel):
            category = discord.utils.get(g.categories, name=config.TICKETS_CATEGORY_NAME) or await g.create_category(
                config.TICKETS_CATEGORY_NAME, overwrites={g.default_role: discord.PermissionOverwrite(view_channel=False)})
            await db.set_setting(g.id, "cat_tickets", category.id)

        perms = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                            attach_files=True, embed_links=True)
        overwrites = {g.default_role: discord.PermissionOverwrite(view_channel=False),
                      interaction.user: perms,
                      g.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)}
        for role in await staff_roles(bot, g):
            overwrites[role] = perms
        channel = await g.create_text_channel(f"заявка-{app_id}", category=category, overwrites=overwrites,
                                              topic=f"app:{app_id}:{interaction.user.id}")
        await db.execute("UPDATE apps SET channel_id=? WHERE id=?", channel.id, app_id)

        applicant = await get_role(bot, g, "role_applicant")
        if applicant:
            try:
                await interaction.user.add_roles(applicant, reason=f"Заявка #{app_id}")
            except discord.Forbidden:
                pass

        row = await db.fetchone("SELECT * FROM apps WHERE id=?", app_id)
        pings = []
        for key in ("role_high", "role_recruiter"):
            r = await get_role(bot, g, key)
            if r and r.mention not in pings:
                pings.append(r.mention)
        await channel.send(content=" ".join(pings) or None, embed=build_embed(g, row, "pending"),
                           view=ReviewView("new"), allowed_mentions=discord.AllowedMentions(roles=True))

        await send_log(bot, g, ui.make(f"📝 Создана заявка {self.kind}",
                                       f"{interaction.user.mention} создал заявку #{app_id} ({self.kind}) • {channel.mention}",
                                       color=config.COLOR_INFO), "ch_log_apps")
        try:
            dm = ui.make("✅ Заявка подана!", f"Ваша {self.kind} заявка #{app_id} успешно создана.", color=GREEN)
            dm.add_field(name="Канал", value=channel.mention, inline=False)
            await interaction.user.send(embed=dm)
        except discord.HTTPException:
            pass
        await interaction.followup.send(f"✅ Заявка #{app_id} ({self.kind}) создана! Канал: {channel.mention}", ephemeral=True)


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
        await finish(interaction, self.row, "denied", "❌ Заявка отклонена", RED, self.reason.value)
        await interaction.followup.send("✅ Заявка отклонена.", ephemeral=True)


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
            except discord.HTTPException as ex:
                return await interaction.response.edit_message(content=f"❌ Ошибка: {ex}", view=None)
        e = ui.make("🔊 Вас вызывают на обзвон!",
                    f"{member.mention}, вас вызывают на обзвон!\nЗайдите в голосовой канал.", color=0x5865F2)
        e.add_field(name="Заявка", value=f"#{self.row['id']}")
        e.add_field(name="Рекрутер", value=interaction.user.mention)
        e.add_field(name="Канал", value=vc.mention)
        ticket = g.get_channel(self.row["channel_id"])
        if ticket:
            await ticket.send(content=member.mention, embed=e)
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
            return await interaction.followup.send("❌ Канал не найден.", ephemeral=True)
        await interaction.followup.send("📄 Транскрипт создан:", file=await transcript_html(ch, self.row["id"]), ephemeral=True)

    @discord.ui.button(label="🔒 Закрыть", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await finish(interaction, self.row, "closed", "🔒 Закрыта заявка", RED)
        await interaction.followup.send("✅ Тикет закрыт!", ephemeral=True)

    @discord.ui.button(label="🗑️ Удалить канал", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.client.db.execute("UPDATE apps SET status='deleted' WHERE id=?", self.row["id"])
        ch = interaction.guild.get_channel(self.row["channel_id"])
        if ch:
            await ch.delete(reason=f"Канал заявки #{self.row['id']} удалён")
        await interaction.followup.send("🗑️ Канал удалён!", ephemeral=True)


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
            await interaction.response.send_message(embed=ui.err("Недостаточно прав."), ephemeral=True)
            return None
        row = await interaction.client.db.fetchone("SELECT * FROM apps WHERE channel_id=?", interaction.channel.id)
        if not row:
            await interaction.response.send_message("❌ Заявка не найдена.", ephemeral=True)
        return row

    @discord.ui.button(label="📝 Взять на рассмотрение", style=discord.ButtonStyle.primary, custom_id="app:take")
    async def take(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await self._guard(interaction)
        if not row:
            return
        await interaction.client.db.execute("UPDATE apps SET status='review', reviewer_id=? WHERE id=?",
                                            interaction.user.id, row["id"])
        await interaction.response.edit_message(embed=build_embed(interaction.guild, row, "review"),
                                                view=ReviewView("review"))
        note = ui.make(f"🟡 Заявка #{row['id']}", f"Заявка взята на рассмотрение {interaction.user.mention}", color=YELLOW)
        note.add_field(name="Статус", value="🟡 На рассмотрении", inline=False)
        await interaction.channel.send(embed=note)
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
        member = g.get_member(row["user_id"])
        if member:
            add = [r for key in ("role_family", "role_newbie") if (r := await get_role(bot, g, key))]
            try:
                if add:
                    await member.add_roles(*add, reason=f"Заявка #{row['id']} принята")
            except discord.Forbidden:
                await interaction.followup.send("⚠️ Не удалось выдать роли — поднимите роль бота выше.", ephemeral=True)
        points = bot.get_cog("Points")
        if points:
            await points.add_points(g.id, row["user_id"], 1.0, interaction.user.id, "TICKET", f"Заявка #{row['id']} принята")
        await dm_result(bot, row["user_id"], "Ваша заявка была **принята ✅**! Добро пожаловать в семью.", GREEN, interaction.user)
        await finish(interaction, row, "accepted", "✅ Заявка принята", GREEN)
        await interaction.followup.send("✅ Заявка принята!", ephemeral=True)

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
            return await interaction.response.send_message("❌ Нет доступных голосовых каналов.", ephemeral=True)
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
