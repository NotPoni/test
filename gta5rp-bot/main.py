import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
import ui
from database import Database

logging.basicConfig(level=logging.INFO)

COGS = [
    "cogs.setup",
    "cogs.general",
    "cogs.applications",
    "cogs.tickets",
    "cogs.hr",
    "cogs.shifts",
    "cogs.capt_menu",
    "cogs.afk",
    "cogs.points",
    "cogs.cabinets",
    "cogs.moderation",
    "cogs.anticrash",
]


class RPBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(
            command_prefix=commands.when_mentioned_or("!"),
            intents=intents,
            help_command=None,
            activity=discord.Game(config.STATUS),
        )
        self.db = Database()

    async def setup_hook(self):
        await self.db.connect()
        for cog in COGS:
            await self.load_extension(cog)
        self.tree.on_error = self.on_tree_error
        if config.GUILD_ID:
            guild = discord.Object(config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self):
        logging.info("Бот запущен как %s", self.user)

    async def on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            text = str(error) or "Недостаточно прав."
        else:
            logging.exception("Ошибка команды", exc_info=error)
            text = "Произошла непредвиденная ошибка."
        embed = ui.err(text)
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, (commands.MissingPermissions, commands.CheckFailure)):
            return await ctx.send(embed=ui.err("Эта команда только для администраторов сервера."))
        if isinstance(error, commands.BadArgument):
            return await ctx.send(embed=ui.err("Неверный аргумент. Пример: `!setup bind role_high @Роль`"))
        logging.exception("Ошибка prefix-команды", exc_info=error)
        await ctx.send(embed=ui.err("Произошла непредвиденная ошибка."))


async def main():
    if not config.TOKEN:
        raise SystemExit("Укажите DISCORD_TOKEN в файле .env")
    async with RPBot() as bot:
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
