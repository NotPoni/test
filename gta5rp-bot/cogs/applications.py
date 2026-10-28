import json
import time

import discord
from discord import app_commands
from discord.ext import commands

import config
import ui
from checks import is_staff

STATUSES = {
    "pending": ("🕓 Ожидает рассмотрения", config.COLOR_WARN),
    "review": ("🔎 На рассмотрении", config.COLOR_INFO),
    "call": ("📞 Вызван на обзвон", config.COLOR_INFO),
    "accepted": ("✅ Принята", config.COLOR_OK),
    "denied": ("❌ Отклонена", config.COLOR_ERR),
}
DM_TEXT = {
    "accepted": "Ваша заявка **одобрена**! Добро пожаловать.",
    "denied": "К сожалению, ваша заявка **отклонена**.",
    "review": "Ваша заявка **взята на рассмотрение**.",
    "call": "Вас **приглашают на обзвон**. Ожидайте сообщения от сотрудников.",
}


def build_embed(user, data, status, reviewer=None, reason=None, app_id=None):
    label, color = STATUSES[status]
    e = ui.make(
        f"📝 Заявка #{app_id}" if app_id else "📝 Новая заявка",
        f"**Кандидат:** {user.mention} (`{user.id}`)\n{ui.DIV}",
        color=color,
        thumbnail=user.display_avatar.url,
    )
    e.add_field(name="👤 Имя Фамилия", value=data["rp_name"])
    e.add_field(name="🆔 Static ID", value=data["static"])
    e.add_field(name="🎂 Возраст (OOC)", value=data["age"])
    e.add_field(name="🎮 Опыт на проектах", value=data["exp"], inline=False)
    e.add_field(name="💬 Почему к нам", value=data["why"], inline=False)
    e.add_field(name="📌 Статус", value=label, inline=False)
    if reviewer:
        e.add_field(name="🛡️ Рассмотрел", value=reviewer.mention)
    if reason:
        e.add_field(name="📄 Причина", value=reason)
    return e


async def finalize(interaction: discord.Interaction, row, status: str, reason: str | None = None):
    db = interaction.client.db
    data = json.loads(row["data"])
    user = interaction.guild.get_member(row["user_id"]) or await interaction.client.fetch_user(row["user_id"])
    await db.execute("UPDATE applications SET status=? WHERE id=?", status, row["id"])
    embed = build_embed(user, data, status, interaction.user, reason, row["id"])
    view = None if status in ("accepted", "denied") else ReviewView()
    await interaction.response.edit_message(embed=embed, view=view)

    dm = ui.make("📨 Статус вашей заявки", DM_TEXT[status], color=STATUSES[status][1])
    dm.add_field(name="Сервер", value=interaction.guild.name)
    if reason:
        dm.add_field(name="Причина", value=reason, inline=False)
    try:
        await user.send(embed=dm)
    except discord.HTTPException:
        pass


class ApplicationModal(discord.ui.Modal, title="Заявка на вступление"):
    rp_name = discord.ui.TextInput(label="Имя Фамилия (RP)", placeholder="John Smith", max_length=40)
    static = discord.ui.TextInput(label="Static ID", placeholder="12345", max_length=10)
    age = discord.ui.TextInput(label="Реальный возраст (OOC)", max_length=3)
    exp = discord.ui.TextInput(label="Опыт на проектах GTA 5RP", style=discord.TextStyle.paragraph, max_length=500)
    why = discord.ui.TextInput(label="Почему хотите к нам?", style=discord.TextStyle.paragraph, max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
        db = interaction.client.db
        g = interaction.guild
        active = await db.fetchone(
            "SELECT id FROM applications WHERE guild_id=? AND user_id=? "
            "AND status IN ('pending','review','call')", g.id, interaction.user.id)
        if active:
            return await interaction.response.send_message(
                embed=ui.err("У вас уже есть активная заявка."), ephemeral=True)

        cid = await db.get_setting(g.id, "apps_channel")
        channel = g.get_channel(cid) if cid else None
        if not channel:
            return await interaction.response.send_message(
                embed=ui.err("Канал заявок не настроен. Администратору нужно выполнить `/настройка`."),
                ephemeral=True)

        data = {
            "rp_name": self.rp_name.value, "static": self.static.value, "age": self.age.value,
            "exp": self.exp.value, "why": self.why.value,
        }
        cur = await db.execute(
            "INSERT INTO applications(guild_id,user_id,data,created) VALUES(?,?,?,?)",
            g.id, interaction.user.id, json.dumps(data, ensure_ascii=False), int(time.time()))
        app_id = cur.lastrowid
        msg = await channel.send(
            embed=build_embed(interaction.user, data, "pending", app_id=app_id), view=ReviewView())
        await db.execute("UPDATE applications SET message_id=? WHERE id=?", msg.id, app_id)
        await interaction.response.send_message(
            embed=ui.ok("Заявка отправлена! Ответ придёт вам в личные сообщения."), ephemeral=True)


class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Подать заявку", emoji="📝", style=discord.ButtonStyle.primary, custom_id="app:open")
    async def open(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ApplicationModal())


class DenyModal(discord.ui.Modal, title="Отклонение заявки"):
    reason = discord.ui.TextInput(label="Причина", style=discord.TextStyle.paragraph, max_length=300)

    def __init__(self, row):
        super().__init__()
        self.row = row

    async def on_submit(self, interaction: discord.Interaction):
        await finalize(interaction, self.row, "denied", self.reason.value)


class ReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _guard(self, interaction: discord.Interaction):
        if not await is_staff(interaction):
            await interaction.response.send_message(embed=ui.err("Недостаточно прав."), ephemeral=True)
            return None
        row = await interaction.client.db.fetchone(
            "SELECT * FROM applications WHERE message_id=?", interaction.message.id)
        if not row:
            await interaction.response.send_message(embed=ui.err("Заявка не найдена в базе."), ephemeral=True)
        return row

    @discord.ui.button(label="Принять", emoji="✅", style=discord.ButtonStyle.success, custom_id="app:accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await self._guard(interaction)
        if not row:
            return
        data = json.loads(row["data"])
        member = interaction.guild.get_member(row["user_id"])
        if member:
            role_id = await interaction.client.db.get_setting(interaction.guild_id, "accepted_role")
            role = interaction.guild.get_role(role_id) if role_id else None
            try:
                if role:
                    await member.add_roles(role, reason="Заявка принята")
                await member.edit(nick=f"{data['rp_name']} | {data['static']}"[:32])
            except discord.Forbidden:
                pass  # роль бота ниже выдаваемой роли / владелец сервера
        await finalize(interaction, row, "accepted")

    @discord.ui.button(label="Отклонить", emoji="❌", style=discord.ButtonStyle.danger, custom_id="app:deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await self._guard(interaction)
        if row:
            await interaction.response.send_modal(DenyModal(row))

    @discord.ui.button(label="На рассмотрение", emoji="🔎", style=discord.ButtonStyle.secondary, custom_id="app:review")
    async def review(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await self._guard(interaction)
        if row:
            await finalize(interaction, row, "review")

    @discord.ui.button(label="Обзвон", emoji="📞", style=discord.ButtonStyle.secondary, custom_id="app:call")
    async def call(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await self._guard(interaction)
        if row:
            await finalize(interaction, row, "call")


class Applications(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(PanelView())
        self.bot.add_view(ReviewView())

    @app_commands.command(name="панель_заявок", description="Отправить панель подачи заявок в этот канал")
    @app_commands.default_permissions(administrator=True)
    async def panel(self, interaction: discord.Interaction):
        e = ui.make(
            "📝 Набор в организацию",
            f"Хочешь стать частью нашей команды?\nНажми кнопку ниже и заполни анкету.\n{ui.DIV}\n"
            "• Отвечай честно и развёрнуто\n• Одна активная заявка на человека\n"
            "• Ответ придёт в личные сообщения — **открой ЛС**",
            banner=True,
        )
        await interaction.channel.send(embed=e, view=PanelView())
        await interaction.response.send_message(embed=ui.ok("Панель отправлена."), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Applications(bot))
