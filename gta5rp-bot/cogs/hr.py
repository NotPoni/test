import discord
from discord import app_commands
from discord.ext import commands

import config
import ui
from checks import get_channel, staff_only


class HR(commands.GroupCog, name="кадры", description="Кадровый учёт организации"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    async def _roles(self, member: discord.Member, add=None, remove=None) -> bool:
        try:
            if remove:
                await member.remove_roles(remove)
            if add:
                await member.add_roles(add)
            return True
        except discord.Forbidden:
            return False

    async def _post(self, interaction: discord.Interaction, embed: discord.Embed, member: discord.Member):
        ch = await get_channel(self.bot, interaction.guild, "hr_channel") or interaction.channel
        await ch.send(content=member.mention, embed=embed)
        await interaction.response.send_message(
            embed=ui.ok(f"Запись опубликована в {ch.mention}."), ephemeral=True)

    @app_commands.command(name="принять", description="Принять сотрудника")
    @app_commands.describe(member="Кого принимаем", rank="Стартовая должность (роль)", static="Static ID")
    @staff_only()
    async def hire(self, interaction: discord.Interaction, member: discord.Member,
                   rank: discord.Role, static: str | None = None):
        done = await self._roles(member, add=rank)
        e = ui.make("📥 Принятие в организацию", color=config.COLOR_OK, thumbnail=member.display_avatar.url)
        e.add_field(name="Сотрудник", value=member.mention)
        e.add_field(name="Должность", value=rank.mention)
        if static:
            e.add_field(name="Static ID", value=static)
        e.add_field(name="Принял", value=interaction.user.mention)
        if not done:
            e.add_field(name="⚠️", value="Не удалось выдать роль — проверьте иерархию ролей бота.", inline=False)
        await self._post(interaction, e, member)

    @app_commands.command(name="повысить", description="Повысить сотрудника")
    @app_commands.describe(new_rank="Новая должность", old_rank="Прежняя должность (снимется)")
    @staff_only()
    async def promote(self, interaction: discord.Interaction, member: discord.Member,
                      new_rank: discord.Role, old_rank: discord.Role | None = None, reason: str | None = None):
        done = await self._roles(member, add=new_rank, remove=old_rank)
        e = ui.make("📈 Повышение", color=config.COLOR_OK, thumbnail=member.display_avatar.url)
        e.add_field(name="Сотрудник", value=member.mention)
        e.add_field(name="Было → Стало", value=f"{old_rank.mention if old_rank else '—'} → {new_rank.mention}")
        e.add_field(name="Причина", value=reason or "—", inline=False)
        e.add_field(name="Выдал", value=interaction.user.mention)
        if not done:
            e.add_field(name="⚠️", value="Роли изменены не полностью — проверьте права бота.", inline=False)
        await self._post(interaction, e, member)

    @app_commands.command(name="понизить", description="Понизить сотрудника")
    @staff_only()
    async def demote(self, interaction: discord.Interaction, member: discord.Member,
                     new_rank: discord.Role, old_rank: discord.Role | None = None, reason: str | None = None):
        done = await self._roles(member, add=new_rank, remove=old_rank)
        e = ui.make("📉 Понижение", color=config.COLOR_WARN, thumbnail=member.display_avatar.url)
        e.add_field(name="Сотрудник", value=member.mention)
        e.add_field(name="Было → Стало", value=f"{old_rank.mention if old_rank else '—'} → {new_rank.mention}")
        e.add_field(name="Причина", value=reason or "—", inline=False)
        e.add_field(name="Выдал", value=interaction.user.mention)
        if not done:
            e.add_field(name="⚠️", value="Роли изменены не полностью — проверьте права бота.", inline=False)
        await self._post(interaction, e, member)

    @app_commands.command(name="уволить", description="Уволить сотрудника")
    @app_commands.describe(rank="Роль, которую нужно снять", reason="Причина увольнения")
    @staff_only()
    async def fire(self, interaction: discord.Interaction, member: discord.Member,
                   reason: str, rank: discord.Role | None = None):
        done = await self._roles(member, remove=rank)
        e = ui.make("📤 Увольнение", color=config.COLOR_ERR, thumbnail=member.display_avatar.url)
        e.add_field(name="Сотрудник", value=member.mention)
        e.add_field(name="Причина", value=reason)
        e.add_field(name="Уволил", value=interaction.user.mention)
        if not done:
            e.add_field(name="⚠️", value="Не удалось снять роль.", inline=False)
        await self._post(interaction, e, member)

    @app_commands.command(name="выговор", description="Выдать выговор сотруднику")
    @staff_only()
    async def reprimand(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        e = ui.make("⚠️ Выговор", color=config.COLOR_WARN, thumbnail=member.display_avatar.url)
        e.add_field(name="Сотрудник", value=member.mention)
        e.add_field(name="Причина", value=reason)
        e.add_field(name="Выдал", value=interaction.user.mention)
        await self._post(interaction, e, member)


async def setup(bot):
    await bot.add_cog(HR(bot))
