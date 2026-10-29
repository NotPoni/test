import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
import ui
from database import Database

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

log = logging.getLogger("gta5rp")


def _setup_logging():
    level = getattr(logging, config.LOG_LEVEL, None)
    if not isinstance(level, int):
        level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%d.%m %H:%M:%S",
    )
    logging.getLogger("discord").setLevel(logging.WARNING)


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
        self.db = Database(config.DB_PATH)

    async def setup_hook(self):
        await self.db.connect()
        for cog in COGS:
            try:
                await self.load_extension(cog)
            except Exception:  # один сломанный cog не должен ронять всего бота
                log.exception("Не удалось загрузить %s", cog)
        # tree.error — официальный способ назначить обработчик ошибок команд
        self.tree.error(self.on_tree_error)
        await self._sync_commands()

    async def _purge_stale_commands(self, guild=None) -> list[str]:
        """Удаляет в Discord команды, которых нет в текущем коде (хвосты старого бота)."""
        try:
            existing = await self.tree.fetch_commands(guild=guild)
        except discord.HTTPException:
            return []
        local = {c.name for c in self.tree.get_commands()}
        removed = []
        for cmd in existing:
            if cmd.name in local:
                continue
            try:
                await cmd.delete()
                removed.append(cmd.name)
            except discord.HTTPException:
                log.debug("Не удалось удалить устаревшую команду %s", cmd.name, exc_info=True)
        return removed

    async def _sync_commands(self):
        """Синхронизация команд с очисткой «хвостов» от других версий бота.

        Если ботом с этим же токеном раньше был старый бот, его команды
        (например /create-mcl) остаются висеть в списке. Без очистки
        Discord их не удаляет, и при нажатии прилетает CommandNotFound.
        """
        try:
            guild = discord.Object(config.GUILD_ID) if config.GUILD_ID else None
            stale = await self._purge_stale_commands(guild)
            if guild is not None:
                # глобальные «хвосты» тоже видны в списке, даже если работаем через guild sync
                stale += await self._purge_stale_commands(None)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
            else:
                synced = await self.tree.sync()
            if stale:
                log.warning("Удалены устаревшие slash-команды: %s", ", ".join(sorted(set(stale))))
            log.info("Slash-команды синхронизированы: %s", len(synced))
        except discord.HTTPException:
            log.exception("Не удалось синхронизировать slash-команды")

    async def on_ready(self):
        log.info("Бот запущен как %s (серверов: %s)", self.user, len(self.guilds))
        if config.GUILD_ID and not self.get_guild(config.GUILD_ID):
            log.warning("GUILD_ID=%s, но бот не состоит в этом сервере", config.GUILD_ID)

    async def close(self):
        try:
            await self.db.close()
        finally:
            await super().close()

    async def _reply(self, interaction: discord.Interaction, embed: discord.Embed):
        """Ответ на interaction с защитой от повторного ответа / протухшего токена."""
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException:
            log.debug("Не удалось отправить ответ на interaction", exc_info=True)

    async def on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            text = f"Слишком часто. Попробуйте через {error.retry_after:.0f} с."
        elif isinstance(error, app_commands.NoPrivateMessage):
            text = "Команда доступна только на сервере."
        elif isinstance(error, app_commands.MissingPermissions):
            text = "У вас нет прав для этой команды."
        elif isinstance(error, app_commands.CommandNotFound):
            # команда осталась в клиенте от старой версии бота с тем же токеном
            log.warning("Нажата устаревшая команда: %s", error)
            text = ("Эта команда устарела и больше не поддерживается. "
                    "Перезапустите Discord (Ctrl+R), чтобы обновить список команд.")
        elif isinstance(error, app_commands.CheckFailure):
            text = str(error) or "Недостаточно прав."
        else:
            log.error("Ошибка slash-команды", exc_info=error)
            text = "Произошла непредвиденная ошибка. Попробуйте позже."
        await self._reply(interaction, ui.err(text))

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, (commands.MissingPermissions, commands.CheckFailure)):
            return await ctx.send(embed=ui.err("Эта команда только для администраторов сервера."))
        if isinstance(error, commands.CommandOnCooldown):
            return await ctx.send(embed=ui.err(f"Слишком часто. Попробуйте через {error.retry_after:.0f} с."))
        if isinstance(error, (commands.BadArgument, commands.MissingRequiredArgument)):
            return await ctx.send(embed=ui.err("Неверный аргумент. Пример: `!setup bind role_high @Роль`"))
        log.error("Ошибка prefix-команды", exc_info=error)
        await ctx.send(embed=ui.err("Произошла непредвиденная ошибка."))


async def main():
    problems = config.validate()
    if problems:
        for p in problems:
            log.error("Конфигурация: %s", p)
        raise SystemExit("Исправьте .env и запустите снова.")

    async with RPBot() as bot:
        try:
            await bot.start(config.TOKEN)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    _setup_logging()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Остановлено пользователем")
