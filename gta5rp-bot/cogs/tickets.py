import asyncio
import io

import discord
from discord import app_commands
from discord.ext import commands

import config
import ui
from checks import is_staff, send_log


class TicketModal(discord.ui.Modal, title="Новое обращение"):
    topic = discord.ui.TextInput(label="Тема", max_length=80)
    desc = discord.ui.TextInput(label="Опишите вопрос", style=discord.TextStyle.paragraph, max_length=800)

    async def on_submit(self, interaction: discord.Interaction):
        g = interaction.guild
        db = interaction.client.db
        for ch in g.text_channels:
            if ch.topic == f"ticket:{interaction.user.id}":
                return await interaction.response.send_message(
                    embed=ui.err(f"У вас уже есть открытое обращение: {ch.mention}"), ephemeral=True)

        cat_id = await db.get_setting(g.id, "ticket_category")
        category = g.get_channel(cat_id) if cat_id else None
        staff_id = await db.get_setting(g.id, "staff_role")
        staff_role = g.get_role(staff_id) if staff_id else None

        perms = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
        overwrites = {
            g.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: perms,
            g.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, manage_messages=True)

        channel = await g.create_text_channel(
            f"тикет-{interaction.user.name}"[:90],
            category=category if isinstance(category, discord.CategoryChannel) else None,
            topic=f"ticket:{interaction.user.id}",
            overwrites=overwrites,
        )
        e = ui.make(f"🎫 {self.topic.value}", self.desc.value, thumbnail=interaction.user.display_avatar.url)
        e.add_field(name="Автор", value=interaction.user.mention)
        e.add_field(name="Статус", value="🟢 Открыт")
        await channel.send(
            content=f"{interaction.user.mention} {staff_role.mention if staff_role else ''}",
            embed=e, view=CloseView(),
            allowed_mentions=discord.AllowedMentions(users=True, roles=True))
        await interaction.response.send_message(
            embed=ui.ok(f"Обращение создано: {channel.mention}"), ephemeral=True)


class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Создать обращение", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="ticket:open")
    async def open(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketModal())


class CloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Закрыть", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        owner_id = (channel.topic or "").removeprefix("ticket:")
        is_owner = owner_id == str(interaction.user.id)
        if not (is_owner or await is_staff(interaction)):
            return await interaction.response.send_message(embed=ui.err("Недостаточно прав."), ephemeral=True)

        await interaction.response.send_message(
            embed=ui.make("🔒 Обращение закрывается", "Канал будет удалён через 5 секунд.", color=config.COLOR_WARN))

        lines = []
        async for m in channel.history(limit=None, oldest_first=True):
            lines.append(f"[{m.created_at:%Y-%m-%d %H:%M}] {m.author}: {m.content}")
        file = discord.File(io.BytesIO("\n".join(lines).encode("utf-8")), filename=f"{channel.name}.txt")
        e = ui.make("📁 Обращение закрыто", color=config.COLOR_INFO)
        e.add_field(name="Канал", value=f"#{channel.name}")
        e.add_field(name="Закрыл", value=interaction.user.mention)
        e.add_field(name="Автор", value=f"<@{owner_id}>" if owner_id.isdigit() else "—")
        log_id = await interaction.client.db.get_setting(interaction.guild_id, "log_channel")
        log_ch = interaction.guild.get_channel(log_id) if log_id else None
        if log_ch:
            await log_ch.send(embed=e, file=file)
        await asyncio.sleep(5)
        await channel.delete(reason=f"Тикет закрыт: {interaction.user}")


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(PanelView())
        self.bot.add_view(CloseView())

    @app_commands.command(name="панель_тикетов", description="Отправить панель обращений в этот канал")
    @app_commands.default_permissions(administrator=True)
    async def panel(self, interaction: discord.Interaction):
        e = ui.make(
            "🎫 Служба поддержки",
            f"Остались вопросы или нужна помощь?\nНажми кнопку — откроется личный канал с администрацией.\n{ui.DIV}\n"
            "После закрытия вся переписка сохраняется в логах.",
            banner=True,
        )
        await interaction.channel.send(embed=e, view=PanelView())
        await interaction.response.send_message(embed=ui.ok("Панель отправлена."), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Tickets(bot))
