import discord
from discord import app_commands
from discord.ext import commands

import config
import ui
from blueprint import TIER_KEYS
from checks import get_channel, get_role, head_only, staff_only

TIER_LABELS = {"role_newbie": "Newbie", "role_main": "Main", "role_tier2": "Tier-2", "role_tier1": "Tier-1"}


class HR(commands.GroupCog, name="кадры", description="Кадровый учёт семьи"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    async def _tiers(self, guild: discord.Guild) -> dict:
        return {k: await get_role(self.bot, guild, k) for k in TIER_KEYS}

    @staticmethod
    def _current(member: discord.Member, tiers: dict) -> int:
        have = {r.id for r in member.roles}
        idx = -1
        for i, key in enumerate(TIER_KEYS):
            if tiers.get(key) and tiers[key].id in have:
                idx = i
        return idx

    async def _set_tier(self, member: discord.Member, key: str, tiers: dict) -> bool:
        family = await get_role(self.bot, member.guild, "role_family")
        remove = [r for k, r in tiers.items() if r and k != key and r in member.roles]
        add = [r for r in (tiers.get(key), family) if r and r not in member.roles]
        try:
            if remove:
                await member.remove_roles(*remove, reason="Кадры")
            if add:
                await member.add_roles(*add, reason="Кадры")
            return True
        except discord.HTTPException:
            return False

    async def _post(self, interaction: discord.Interaction, embed: discord.Embed, member: discord.Member, ok=True):
        if not ok:
            embed.add_field(name="⚠️", value="Роли изменены не полностью — поднимите роль бота выше.", inline=False)
        ch = await get_channel(self.bot, interaction.guild, "ch_hr") or interaction.channel
        try:
            await ch.send(content=member.mention, embed=embed)
        except discord.HTTPException:
            return await interaction.response.send_message(
                embed=ui.err("Не удалось опубликовать запись в канале кадров."), ephemeral=True)
        await interaction.response.send_message(embed=ui.ok(f"Запись опубликована в {ch.mention}."), ephemeral=True)

    def _card(self, title, color, member, interaction, **fields):
        e = ui.make(title, color=color, thumbnail=member.display_avatar.url)
        e.add_field(name="Сотрудник", value=member.mention)
        for name, value in fields.items():
            e.add_field(name=name.replace("_", " "), value=ui.cut(value, 1024), inline=name in ("Ранг", "Static_ID"))
        e.add_field(name="Выдал", value=interaction.user.mention)
        return e

    @app_commands.command(name="принять", description="Принять в семью (Newbie + роль семьи)")
    @app_commands.describe(member="Кого принимаем", static="Static ID")
    @app_commands.guild_only()
    @staff_only()
    async def hire(self, interaction: discord.Interaction, member: discord.Member, static: str | None = None):
        if member.bot:
            return await interaction.response.send_message(embed=ui.err("Бота принять нельзя."), ephemeral=True)
        tiers = await self._tiers(interaction.guild)
        if not tiers.get("role_newbie"):
            return await interaction.response.send_message(
                embed=ui.err("Роль Newbie не привязана. Запустите `!setup`."), ephemeral=True)
        ok = await self._set_tier(member, "role_newbie", tiers)
        applicant = await get_role(self.bot, interaction.guild, "role_applicant")
        if applicant and applicant in member.roles:
            try:
                await member.remove_roles(applicant)
            except discord.HTTPException:
                ok = False
        fields = {"Ранг": "Newbie"}
        if static:
            fields["Static_ID"] = static
        await self._post(interaction, self._card("📥 Принятие в семью", config.COLOR_OK, member, interaction, **fields), member, ok)

    @app_commands.command(name="повысить", description="Повысить на ступень: Newbie → Main → Tier-2 → Tier-1")
    @app_commands.guild_only()
    @head_only()
    async def promote(self, interaction: discord.Interaction, member: discord.Member, reason: str | None = None):
        tiers = await self._tiers(interaction.guild)
        cur = self._current(member, tiers)
        if cur >= len(TIER_KEYS) - 1:
            return await interaction.response.send_message(embed=ui.err("Уже максимальный ранг."), ephemeral=True)
        new = TIER_KEYS[cur + 1]
        if not tiers.get(new):
            return await interaction.response.send_message(embed=ui.err("Роль ранга не привязана. `!setup`."), ephemeral=True)
        ok = await self._set_tier(member, new, tiers)
        old = TIER_LABELS[TIER_KEYS[cur]] if cur >= 0 else "—"
        e = self._card("📈 Повышение", config.COLOR_OK, member, interaction,
                       Было_Стало=f"{old} → **{TIER_LABELS[new]}**", Причина=reason or "—")
        await self._post(interaction, e, member, ok)

    @app_commands.command(name="понизить", description="Понизить на ступень")
    @app_commands.guild_only()
    @head_only()
    async def demote(self, interaction: discord.Interaction, member: discord.Member, reason: str | None = None):
        tiers = await self._tiers(interaction.guild)
        cur = self._current(member, tiers)
        if cur <= 0:
            return await interaction.response.send_message(
                embed=ui.err("Ниже опускаться некуда — используйте `/кадры уволить`."), ephemeral=True)
        new = TIER_KEYS[cur - 1]
        ok = await self._set_tier(member, new, tiers)
        e = self._card("📉 Понижение", config.COLOR_WARN, member, interaction,
                       Было_Стало=f"{TIER_LABELS[TIER_KEYS[cur]]} → **{TIER_LABELS[new]}**", Причина=reason or "—")
        await self._post(interaction, e, member, ok)

    @app_commands.command(name="ранг", description="Выставить ранг напрямую")
    @app_commands.choices(rank=[app_commands.Choice(name=v, value=k) for k, v in TIER_LABELS.items()])
    @app_commands.guild_only()
    @head_only()
    async def set_rank(self, interaction: discord.Interaction, member: discord.Member,
                       rank: app_commands.Choice[str], reason: str | None = None):
        tiers = await self._tiers(interaction.guild)
        if not tiers.get(rank.value):
            return await interaction.response.send_message(embed=ui.err("Роль ранга не привязана. `!setup`."), ephemeral=True)
        ok = await self._set_tier(member, rank.value, tiers)
        e = self._card("🎖️ Смена ранга", config.COLOR_INFO, member, interaction, Ранг=rank.name, Причина=reason or "—")
        await self._post(interaction, e, member, ok)

    @app_commands.command(name="уволить", description="Уволить: снять ранги и роль семьи")
    @app_commands.guild_only()
    @head_only()
    async def fire(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        tiers = await self._tiers(interaction.guild)
        extra = [await get_role(self.bot, interaction.guild, k)
                 for k in ("role_family", "role_afk", "role_inactive", "role_applicant")]
        remove = [r for r in list(tiers.values()) + extra if r and r in member.roles]
        ok = True
        try:
            if remove:
                await member.remove_roles(*remove, reason=f"Увольнение: {reason}")
        except discord.HTTPException:
            ok = False
        e = self._card("📤 Увольнение", config.COLOR_ERR, member, interaction, Причина=reason)
        await self._post(interaction, e, member, ok)

    @app_commands.command(name="выговор", description="Выдать выговор")
    @app_commands.guild_only()
    @head_only()
    async def reprimand(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        e = self._card("⚠️ Выговор", config.COLOR_WARN, member, interaction, Причина=reason)
        await self._post(interaction, e, member)


async def setup(bot):
    await bot.add_cog(HR(bot))
