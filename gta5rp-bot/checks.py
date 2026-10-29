import io

import discord
from discord import app_commands

import config

STAFF_KEYS = ("role_owner", "role_dep_owner", "role_high", "role_recruiter")
HEAD_KEYS = ("role_owner", "role_dep_owner", "role_high")


async def role_ids(bot, guild_id: int, keys) -> set[int]:
    out = set()
    for k in keys:
        rid = await bot.db.get_setting(guild_id, k)
        if rid:
            out.add(rid)
    return out


async def level(bot, member) -> int:
    """2 — руководство, 1 — сотрудник (рекрутер), 0 — обычный участник."""
    if not isinstance(member, discord.Member):
        return 0
    if member.guild_permissions.administrator or member.id == member.guild.owner_id:
        return 2
    have = {r.id for r in member.roles}
    if have & set(config.STAFF_EXTRA_ROLE_IDS):
        return 2
    if have & await role_ids(bot, member.guild.id, HEAD_KEYS):
        return 2
    if have & await role_ids(bot, member.guild.id, STAFF_KEYS):
        return 1
    return 0


async def is_staff(interaction: discord.Interaction) -> bool:
    return await level(interaction.client, interaction.user) >= 1


async def is_head(interaction: discord.Interaction) -> bool:
    return await level(interaction.client, interaction.user) >= 2


def staff_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        if await is_staff(interaction):
            return True
        raise app_commands.CheckFailure("Эта команда доступна только сотрудникам.")
    return app_commands.check(predicate)


def head_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        if await is_head(interaction):
            return True
        raise app_commands.CheckFailure("Эта команда доступна только руководству.")
    return app_commands.check(predicate)


async def get_role(bot, guild: discord.Guild, key: str) -> discord.Role | None:
    rid = await bot.db.get_setting(guild.id, key)
    return guild.get_role(rid) if rid else None


async def get_channel(bot, guild: discord.Guild, key: str):
    cid = await bot.db.get_setting(guild.id, key)
    return guild.get_channel(cid) if cid else None


async def staff_roles(bot, guild: discord.Guild) -> list[discord.Role]:
    ids = await role_ids(bot, guild.id, STAFF_KEYS) | set(config.STAFF_EXTRA_ROLE_IDS)
    return [r for rid in ids if (r := guild.get_role(rid))]


async def send_log(bot, guild: discord.Guild, embed: discord.Embed, key: str = "ch_log", **kwargs):
    ch = await get_channel(bot, guild, key)
    if ch is None and key != "ch_log":
        ch = await get_channel(bot, guild, "ch_log")
    if ch:
        try:
            await ch.send(embed=embed, **kwargs)
        except discord.HTTPException:
            pass


async def transcript_file(channel: discord.TextChannel) -> discord.File:
    lines = []
    async for m in channel.history(limit=None, oldest_first=True):
        text = m.content or ""
        if m.embeds and not text:
            text = "[embed] " + (m.embeds[0].title or "")
        lines.append(f"[{m.created_at:%Y-%m-%d %H:%M}] {m.author}: {text}")
    return discord.File(io.BytesIO("\n".join(lines).encode("utf-8")), filename=f"{channel.name}.txt")
