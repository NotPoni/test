import logging

import discord
from discord import app_commands
from discord.ext import commands

from config import cfg
from db import DB
from health import start_health_server
from utils import deny

COGS = [
    "cogs.protection",
    "cogs.applications",
    "cogs.events",
    "cogs.stats",
    "cogs.warns",
    "cogs.shop",
    "cogs.interactions",
    "cogs.lists",
    "cogs.setup_cmd",
]

log = logging.getLogger("void")


class VoidBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True          # Server Members Intent
        intents.message_content = True  # Message Content Intent (пинги everyone/here)
        super().__init__(command_prefix="!", intents=intents)
        self.db = DB(cfg.db_path)
        self.tree.on_error = self.on_tree_error
        self._health = None

    async def setup_hook(self):
        await self.db.connect()
        for name in COGS:
            # Сбой одного модуля не должен валить весь бот
            try:
                await self.load_extension(name)
            except Exception:
                log.exception("Модуль %s не загружен, остальные работают", name)

        guild = discord.Object(id=cfg.guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

        if cfg.port:
            try:
                self._health = await start_health_server(cfg.host, cfg.port)
            except OSError as e:
                log.warning("Health-сервер не запущен: %s", e)

    async def on_ready(self):
        log.info("Logged in as %s", self.user)

    async def on_tree_error(self, interaction, error):
        if isinstance(error, app_commands.CheckFailure):
            msg = str(error) if str(error) else "Нет доступа."
        else:
            log.error("Command error", exc_info=error)
            msg = "Произошла ошибка."
        await deny(interaction, msg)

    async def close(self):
        if self._health:
            await self._health.cleanup()
        await self.db.close()
        await super().close()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if not cfg.token or not cfg.guild_id:
        raise SystemExit("Заполните DISCORD_TOKEN и GUILD_ID в .env")
    VoidBot().run(cfg.token)


if __name__ == "__main__":
    main()
