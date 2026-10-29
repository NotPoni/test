import asyncio
import logging

import discord
from discord.ext import commands

import config
import texts
import ui
from checks import get_channel, is_staff, staff_roles, transcript_file

log = logging.getLogger(__name__)


class TicketModal(discord.ui.Modal, title="Новое обращение"):
    topic = discord.ui.TextInput(label="Тема", max_length=80)
    desc = discord.ui.TextInput(label="Опишите вопрос", style=discord.TextStyle.paragraph, max_length=800)

    async def on_submit(self, interaction: discord.Interaction):
        bot, g = interaction.client, interaction.guild
        if g is None:
            return await interaction.response.send_message(embed=ui.err("Только на сервере."), ephemeral=True)
        for ch in g.text_channels:
            if ch.topic == f"ticket:{interaction.user.id}":
                return await interaction.response.send_message(
                    embed=ui.err(f"У вас уже есть открытое обращение: {ch.mention}"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        category = await get_channel(bot, g, "cat_tickets")
        perms = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                            attach_files=True)
        overwrites = {
            g.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: perms,
            g.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        staff = await staff_roles(bot, g)
        for role in staff:
            overwrites[role] = perms
        try:
            channel = await g.create_text_channel(
                f"тикет-{interaction.user.name}"[:90],
                category=category if isinstance(category, discord.CategoryChannel) else None,
                topic=f"ticket:{interaction.user.id}", overwrites=overwrites)
        except discord.HTTPException:
            return await interaction.followup.send(embed=ui.err("Не удалось создать канал обращения."), ephemeral=True)

        e = ui.make(f"🎫 {self.topic.value}", self.desc.value, thumbnail=interaction.user.display_avatar.url)
        e.add_field(name="Автор", value=interaction.user.mention)
        e.add_field(name="Статус", value="🟢 Открыт")
        pings = " ".join(r.mention for r in staff if r.mentionable)
        try:
            await channel.send(content=f"{interaction.user.mention} {pings}".strip(), embed=e, view=CloseView(),
                               allowed_mentions=discord.AllowedMentions(users=True, roles=True))
        except discord.HTTPException:
            pass
        await interaction.followup.send(embed=ui.ok(f"Обращение создано: {channel.mention}"), ephemeral=True)


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
        owner_id = (channel.topic or "").removeprefix("ticket:") if isinstance(channel, discord.TextChannel) else ""
        if not (owner_id == str(interaction.user.id) or await is_staff(interaction)):
            return await interaction.response.send_message(embed=ui.err("Недостаточно прав."), ephemeral=True)
        await interaction.response.send_message(
            embed=ui.make("🔒 Обращение закрывается", "Канал будет удалён через 5 секунд.", color=config.COLOR_WARN))
        e = ui.make("📁 Обращение закрыто", color=config.COLOR_INFO)
        e.add_field(name="Канал", value=f"#{channel.name}")
        e.add_field(name="Закрыл", value=interaction.user.mention)
        e.add_field(name="Автор", value=f"<@{owner_id}>" if owner_id.isdigit() else "—")
        logch = await get_channel(interaction.client, interaction.guild, "ch_log")
        if logch:
            try:
                await logch.send(embed=e, file=await transcript_file(channel))
            except discord.HTTPException:
                try:
                    await logch.send(embed=e)
                except discord.HTTPException:
                    pass
        await asyncio.sleep(5)
        try:
            await channel.delete(reason=f"Тикет закрыт: {interaction.user}")
        except discord.HTTPException:
            log.warning("Не удалось удалить канал тикета %s", channel.id)


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(PanelView())
        self.bot.add_view(CloseView())

    async def post_panel(self, channel, key):
        e = ui.make("🆘 Служба поддержки", f"{texts.SUPPORT_INFO}\n{ui.DIV}\n"
                    "После закрытия вся переписка сохраняется в логах.", banner=True)
        await channel.send(embed=e, view=PanelView())


async def setup(bot):
    await bot.add_cog(Tickets(bot))
