import discord
from discord import app_commands
from discord.ext import commands

import config
import ui
from checks import get_channel, send_log


class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="помощь", description="Список возможностей бота")
    async def help_cmd(self, interaction: discord.Interaction):
        e = ui.make("📖 Возможности бота", f"Всё для вашего сервера GTA 5RP\n{ui.DIV}", banner=True)
        e.add_field(name="📝 Заявки", value="`/панель_заявок` — форма вступления, рассмотрение кнопками", inline=False)
        e.add_field(name="🎫 Тикеты", value="`/панель_тикетов` — обращения с логом переписки", inline=False)
        e.add_field(name="📋 Кадры", value="`/кадры принять|повысить|понизить|уволить|выговор`", inline=False)
        e.add_field(name="⏱️ Смены", value="`/панель_смен` — учёт смен, онлайн и топ", inline=False)
        e.add_field(name="📅 Сборы", value="`/сбор` — запись на мероприятие кнопками", inline=False)
        e.add_field(name="🔨 Модерация", value="`/варн` `/варны` `/мут` `/размут` `/бан` `/очистить`", inline=False)
        e.add_field(name="🛡️ Анти-краш", value="Защита от массового удаления каналов/ролей, банов и левых ботов", inline=False)
        e.add_field(name="⚙️ Настройка", value="`/настройка` — роли и каналы (админ)", inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        ch = await get_channel(self.bot, member.guild, "welcome_channel")
        if not ch or member.bot:
            return
        e = ui.make(
            "👋 Добро пожаловать!",
            f"{member.mention}, рады видеть тебя на **{member.guild.name}**!\n"
            f"Ты — участник №**{member.guild.member_count}**.\n{ui.DIV}\n"
            "Подай заявку или создай обращение в соответствующих каналах.",
            thumbnail=member.display_avatar.url,
            banner=True,
        )
        await ch.send(content=member.mention, embed=e)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        e = ui.make("🗑️ Сообщение удалено", color=config.COLOR_ERR)
        e.add_field(name="Автор", value=message.author.mention)
        e.add_field(name="Канал", value=message.channel.mention)
        e.add_field(name="Текст", value=(message.content or "—")[:1000], inline=False)
        await send_log(self.bot, message.guild, e)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot or before.content == after.content:
            return
        e = ui.make("✏️ Сообщение изменено", color=config.COLOR_WARN)
        e.add_field(name="Автор", value=before.author.mention)
        e.add_field(name="Канал", value=before.channel.mention)
        e.add_field(name="Было", value=(before.content or "—")[:1000], inline=False)
        e.add_field(name="Стало", value=(after.content or "—")[:1000], inline=False)
        await send_log(self.bot, before.guild, e)


async def setup(bot):
    await bot.add_cog(General(bot))
