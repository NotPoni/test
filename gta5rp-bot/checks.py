import discord
from discord import app_commands


async def is_staff(interaction: discord.Interaction) -> bool:
    m = interaction.user
    if not isinstance(m, discord.Member):
        return False
    if m.guild_permissions.administrator:
        return True
    rid = await interaction.client.db.get_setting(interaction.guild_id, "staff_role")
    return bool(rid and m.get_role(rid))


def staff_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        if await is_staff(interaction):
            return True
        raise app_commands.CheckFailure("Эта команда доступна только сотрудникам.")
    return app_commands.check(predicate)


async def get_channel(bot, guild: discord.Guild, key: str):
    cid = await bot.db.get_setting(guild.id, key)
    return guild.get_channel(cid) if cid else None


async def send_log(bot, guild: discord.Guild, embed: discord.Embed, **kwargs):
    ch = await get_channel(bot, guild, "log_channel")
    if ch:
        try:
            await ch.send(embed=embed, **kwargs)
        except discord.HTTPException:
            pass
