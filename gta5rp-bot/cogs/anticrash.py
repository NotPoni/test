import time
from collections import defaultdict, deque

import discord
from discord.ext import commands

import config
import ui
from checks import send_log

LIMITS = {"channel_delete": 3, "channel_create": 8, "role_delete": 3, "ban": 4, "kick": 4}
WINDOW = 30  # секунд


class AntiCrash(commands.Cog):
    """Защита от краша: массовые удаления/баны и добавление сторонних ботов."""

    def __init__(self, bot):
        self.bot = bot
        self.history = defaultdict(deque)

    async def _executor(self, guild: discord.Guild, action, target_id=None):
        try:
            async for entry in guild.audit_logs(limit=6, action=action):
                fresh = (discord.utils.utcnow() - entry.created_at).total_seconds() < 10
                if fresh and (target_id is None or getattr(entry.target, "id", None) == target_id):
                    return entry.user
        except discord.Forbidden:
            return None
        return None

    def _trusted(self, guild, user) -> bool:
        return user.id == self.bot.user.id or user.id == guild.owner_id or user.id in config.WHITELIST

    async def _hit(self, guild, user, key):
        if user is None or self._trusted(guild, user):
            return
        dq = self.history[(guild.id, user.id, key)]
        now = time.monotonic()
        dq.append(now)
        while dq and now - dq[0] > WINDOW:
            dq.popleft()
        if len(dq) >= LIMITS[key]:
            dq.clear()
            await self._punish(guild, user, f"массовое действие: {key}")

    async def _punish(self, guild, user, why):
        member = guild.get_member(user.id)
        result = "не удалось наказать (проверьте иерархию ролей бота)"
        if member:
            try:
                await member.ban(reason=f"Anti-crash: {why}", delete_message_seconds=0)
                result = "забанен"
            except discord.Forbidden:
                try:
                    await member.remove_roles(*[r for r in member.roles if r.is_assignable()],
                                              reason=f"Anti-crash: {why}")
                    result = "лишён ролей"
                except discord.Forbidden:
                    pass
        e = ui.make("🛡️ Anti-crash", color=config.COLOR_ERR)
        e.add_field(name="Нарушитель", value=f"{user.mention} (`{user.id}`)")
        e.add_field(name="Причина", value=why)
        e.add_field(name="Результат", value=result, inline=False)
        await send_log(self.bot, guild, e, content=f"<@{guild.owner_id}>")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        user = await self._executor(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        await self._hit(channel.guild, user, "channel_delete")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        user = await self._executor(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        await self._hit(channel.guild, user, "channel_create")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        user = await self._executor(role.guild, discord.AuditLogAction.role_delete, role.id)
        await self._hit(role.guild, user, "role_delete")

    @commands.Cog.listener()
    async def on_member_ban(self, guild, banned):
        user = await self._executor(guild, discord.AuditLogAction.ban, banned.id)
        await self._hit(guild, user, "ban")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        user = await self._executor(member.guild, discord.AuditLogAction.kick, member.id)
        await self._hit(member.guild, user, "kick")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not member.bot:
            return
        adder = await self._executor(member.guild, discord.AuditLogAction.bot_add, member.id)
        if adder and self._trusted(member.guild, adder):
            return
        try:
            await member.kick(reason="Anti-crash: добавление стороннего бота")
        except discord.Forbidden:
            pass
        e = ui.make("🛡️ Сторонний бот удалён", color=config.COLOR_ERR)
        e.add_field(name="Бот", value=f"{member} (`{member.id}`)")
        e.add_field(name="Добавил", value=adder.mention if adder else "неизвестно")
        await send_log(self.bot, member.guild, e)
        if adder:
            await self._punish(member.guild, adder, "добавление стороннего бота")


async def setup(bot):
    await bot.add_cog(AntiCrash(bot))
