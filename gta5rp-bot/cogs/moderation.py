import time
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

import config
import ui
from checks import head_only, send_log, staff_only


def can_act(interaction: discord.Interaction, target: discord.Member) -> bool:
    if interaction.user.id == interaction.guild.owner_id:
        return True
    return target.top_role < interaction.user.top_role and target.id != interaction.guild.owner_id


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _report(self, interaction, title, member, reason, color, extra=None):
        e = ui.make(title, color=color, thumbnail=member.display_avatar.url)
        e.add_field(name="Пользователь", value=f"{member.mention} (`{member.id}`)")
        e.add_field(name="Модератор", value=interaction.user.mention)
        if extra:
            e.add_field(name="Срок", value=extra)
        e.add_field(name="Причина", value=reason, inline=False)
        await interaction.response.send_message(embed=e)
        await send_log(self.bot, interaction.guild, e)

    @staticmethod
    async def _deny(interaction):
        await interaction.response.send_message(embed=ui.err("Нельзя наказать этого пользователя."), ephemeral=True)

    @app_commands.command(name="варн", description="Выдать предупреждение")
    @staff_only()
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        if not can_act(interaction, member):
            return await self._deny(interaction)
        await self.bot.db.execute("INSERT INTO warns(guild_id,user_id,mod_id,reason,ts) VALUES(?,?,?,?,?)",
                                  interaction.guild_id, member.id, interaction.user.id, reason, int(time.time()))
        cnt = (await self.bot.db.fetchone("SELECT COUNT(*) c FROM warns WHERE guild_id=? AND user_id=?",
                                          interaction.guild_id, member.id))["c"]
        try:
            await member.send(embed=ui.make("⚠️ Вам выдано предупреждение",
                                            f"Сервер: **{interaction.guild.name}**\nПричина: {reason}\nВсего варнов: **{cnt}**",
                                            color=config.COLOR_WARN))
        except discord.HTTPException:
            pass
        await self._report(interaction, f"⚠️ Предупреждение ({cnt})", member, reason, config.COLOR_WARN)

    @app_commands.command(name="варны", description="Список предупреждений пользователя")
    @staff_only()
    async def warns(self, interaction: discord.Interaction, member: discord.Member):
        rows = await self.bot.db.fetchall(
            "SELECT id,mod_id,reason,ts FROM warns WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 15",
            interaction.guild_id, member.id)
        text = "\n".join(f"`#{r['id']}` <t:{r['ts']}:d> — {r['reason']} (<@{r['mod_id']}>)" for r in rows) or "Нет предупреждений."
        await interaction.response.send_message(
            embed=ui.make(f"📋 Варны {member.display_name}", text, thumbnail=member.display_avatar.url), ephemeral=True)

    @app_commands.command(name="снять_варн", description="Удалить предупреждение по номеру")
    @staff_only()
    async def unwarn(self, interaction: discord.Interaction, warn_id: int):
        await self.bot.db.execute("DELETE FROM warns WHERE id=? AND guild_id=?", warn_id, interaction.guild_id)
        await interaction.response.send_message(embed=ui.ok(f"Предупреждение #{warn_id} удалено."), ephemeral=True)

    @app_commands.command(name="мут", description="Выдать тайм-аут")
    @app_commands.describe(minutes="Минут (до 40320 = 28 дней)")
    @staff_only()
    async def mute(self, interaction: discord.Interaction, member: discord.Member,
                   minutes: app_commands.Range[int, 1, 40320], reason: str):
        if not can_act(interaction, member):
            return await self._deny(interaction)
        await member.timeout(timedelta(minutes=minutes), reason=reason)
        await self._report(interaction, "🔇 Мут", member, reason, config.COLOR_WARN, ui.fmt_minutes(minutes))

    @app_commands.command(name="размут", description="Снять тайм-аут")
    @staff_only()
    async def unmute(self, interaction: discord.Interaction, member: discord.Member):
        await member.timeout(None)
        await interaction.response.send_message(embed=ui.ok(f"{member.mention} размучен."))

    @app_commands.command(name="бан", description="Забанить пользователя")
    @head_only()
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        if not can_act(interaction, member):
            return await self._deny(interaction)
        await member.ban(reason=f"{interaction.user}: {reason}")
        await self._report(interaction, "🔨 Бан", member, reason, config.COLOR_ERR)

    @app_commands.command(name="очистить", description="Удалить последние сообщения")
    @staff_only()
    async def clear(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(embed=ui.ok(f"Удалено сообщений: **{len(deleted)}**"), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
