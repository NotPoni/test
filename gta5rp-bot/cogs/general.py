import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
import texts
import ui
from checks import get_channel, send_log

SPECT = "!SPECT "
log = logging.getLogger(__name__)


class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def post_panel(self, channel, key):
        if key == "ch_rules":
            e = ui.make("📜 Правила сервера", f"{texts.RULES}\n{ui.DIV}", banner=True)
            await channel.send(embed=e)

    @app_commands.command(name="помощь", description="Список возможностей бота")
    async def help_cmd(self, interaction: discord.Interaction):
        e = ui.make("📖 Возможности бота", f"Всё для семьи в GTA 5RP\n{ui.DIV}", banner=True)
        e.add_field(name="⚙️ Настройка (админ)", value="`!setup` — создать роли/каналы/панели • `!setup status` • "
                                                       "`!setup panels` • `!panel <имя>`", inline=False)
        e.add_field(name="📝 Заявки", value="RP+CAPT и RP • рассмотрение, обзвон, транскрипт • принятие выдаёт роли и баллы", inline=False)
        e.add_field(name="🎫 Тикеты", value="Канал поддержки с логом переписки", inline=False)
        e.add_field(name="🎯 CAPT", value="`/capt` — меню с веткой, реакции ✅/❌, баллы за участие", inline=False)
        e.add_field(name="🕒 AFK", value="Инактив-панель: AFK, Инактив, Вернулся, Модерация • предупреждения в #варны", inline=False)
        e.add_field(name="🏆 Баллы", value="`/баллы` `/топ` + магазин, баллы за голос и события", inline=False)
        e.add_field(name="📋 Кадры", value="`/кадры принять|повысить|понизить|ранг|уволить|выговор`", inline=False)
        e.add_field(name="📁 Кабинеты", value="Личный канал с ветками, статистикой и откатами", inline=False)
        e.add_field(name="🔨 Модерация", value="`/варн` `/варны` `/мут` `/размут` `/бан` `/очистить`", inline=False)
        e.add_field(name="🛡️ Анти-краш", value="Работает автоматически", inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="spect", description="Добавить префикс !SPECT к нику")
    @app_commands.guild_only()
    async def spect(self, interaction: discord.Interaction):
        m = interaction.user
        name = m.display_name
        if name.startswith(SPECT):
            return await interaction.response.send_message(embed=ui.err("Префикс уже стоит."), ephemeral=True)
        try:
            await m.edit(nick=(SPECT + name)[:32])
        except discord.HTTPException:
            return await interaction.response.send_message(embed=ui.err("Не могу изменить ваш ник."), ephemeral=True)
        await interaction.response.send_message(embed=ui.ok("Префикс **!SPECT** добавлен."), ephemeral=True)

    @app_commands.command(name="unspect", description="Убрать префикс !SPECT из ника")
    @app_commands.guild_only()
    async def unspect(self, interaction: discord.Interaction):
        m = interaction.user
        if not m.display_name.startswith(SPECT):
            return await interaction.response.send_message(embed=ui.err("Префикса нет."), ephemeral=True)
        try:
            await m.edit(nick=m.display_name[len(SPECT):] or None)
        except discord.HTTPException:
            return await interaction.response.send_message(embed=ui.err("Не могу изменить ваш ник."), ephemeral=True)
        await interaction.response.send_message(embed=ui.ok("Префикс убран."), ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        e = ui.make("📥 Участник зашёл", f"{member.mention} (`{member.id}`)", color=config.COLOR_OK,
                    thumbnail=member.display_avatar.url)
        await send_log(self.bot, member.guild, e)
        ch = await get_channel(self.bot, member.guild, "ch_welcome")
        if not ch or member.bot:
            return
        w = ui.make(
            "👋 Добро пожаловать!",
            f"{member.mention}, рады видеть тебя на **{member.guild.name}**!\n"
            f"Ты — участник №**{member.guild.member_count}**.\n{ui.DIV}\n"
            "Хочешь в семью? Загляни в канал заявок.",
            thumbnail=member.display_avatar.url, banner=True)
        try:
            await ch.send(content=member.mention, embed=w)
        except discord.HTTPException:
            log.warning("Не удалось отправить приветствие в %s", ch.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        e = ui.make("📤 Участник вышел", f"{member} (`{member.id}`)", color=config.COLOR_ERR,
                    thumbnail=member.display_avatar.url)
        await send_log(self.bot, member.guild, e)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        e = ui.make("🗑️ Сообщение удалено", color=config.COLOR_ERR)
        e.add_field(name="Автор", value=message.author.mention)
        e.add_field(name="Канал", value=message.channel.mention)
        e.add_field(name="Текст", value=ui.cut(message.content or "—", 1000), inline=False)
        await send_log(self.bot, message.guild, e)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot or before.content == after.content:
            return
        e = ui.make("✏️ Сообщение изменено", color=config.COLOR_WARN)
        e.add_field(name="Автор", value=before.author.mention)
        e.add_field(name="Канал", value=before.channel.mention)
        e.add_field(name="Было", value=ui.cut(before.content or "—", 1000), inline=False)
        e.add_field(name="Стало", value=ui.cut(after.content or "—", 1000), inline=False)
        await send_log(self.bot, before.guild, e)


async def setup(bot):
    await bot.add_cog(General(bot))
