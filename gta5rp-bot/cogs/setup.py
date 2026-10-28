import discord
from discord import app_commands
from discord.ext import commands

import ui

KEYS = {
    "staff_role": "👮 Роль сотрудников",
    "accepted_role": "🎖️ Роль после принятия",
    "apps_channel": "📝 Канал заявок",
    "log_channel": "📜 Канал логов",
    "hr_channel": "📋 Канал кадровых записей",
    "welcome_channel": "👋 Канал приветствий",
    "ticket_category": "🎫 Категория тикетов",
}


class Setup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="настройка", description="Настроить роли и каналы бота")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        staff_role="Роль сотрудников/модераторов",
        accepted_role="Роль, которая выдаётся при принятии заявки",
        apps_channel="Канал, куда приходят заявки",
        log_channel="Канал логов",
        hr_channel="Канал кадровых записей",
        welcome_channel="Канал приветствий",
        ticket_category="Категория для тикетов",
    )
    async def setup_cmd(
        self,
        interaction: discord.Interaction,
        staff_role: discord.Role | None = None,
        accepted_role: discord.Role | None = None,
        apps_channel: discord.TextChannel | None = None,
        log_channel: discord.TextChannel | None = None,
        hr_channel: discord.TextChannel | None = None,
        welcome_channel: discord.TextChannel | None = None,
        ticket_category: discord.CategoryChannel | None = None,
    ):
        values = locals()
        for key in KEYS:
            if values[key] is not None:
                await self.bot.db.set_setting(interaction.guild_id, key, values[key].id)

        lines = []
        for key, label in KEYS.items():
            vid = await self.bot.db.get_setting(interaction.guild_id, key)
            if vid is None:
                lines.append(f"{label}: `не задано`")
            elif key.endswith("role"):
                lines.append(f"{label}: <@&{vid}>")
            else:
                lines.append(f"{label}: <#{vid}>")
        embed = ui.make("⚙️ Настройки бота", "\n".join(lines))
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Setup(bot))
