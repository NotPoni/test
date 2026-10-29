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
    # один запрос вместо шести: все привязки ролей сервера
    settings = await bot.db.settings_like(member.guild.id, "role_")
    head = {settings[k] for k in HEAD_KEYS if k in settings}
    if have & head:
        return 2
    staff = {settings[k] for k in STAFF_KEYS if k in settings}
    return 1 if have & staff else 0


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
    """Отправка в лог-канал; молча пропускает отсутствующий канал и ошибки прав."""
    if guild is None:
        return
    ch = await get_channel(bot, guild, key)
    if ch is None and key != "ch_log":
        ch = await get_channel(bot, guild, "ch_log")
    if ch:
        try:
            await ch.send(embed=embed, **kwargs)
        except discord.HTTPException:
            pass


def _message_text(message: discord.Message) -> str:
    parts = [message.content or ""]
    for e in message.embeds:
        if e.title:
            parts.append(f"[embed] {e.title}")
        if e.description:
            parts.append(f"[embed] {e.description}")
        for f in e.fields:
            parts.append(f"[embed] {f.name}: {f.value}")
    for a in message.attachments:
        parts.append(f"[файл] {a.url}")
    return " ".join(p for p in parts if p).strip() or "—"


async def transcript_file(channel: discord.TextChannel) -> discord.File:
    lines = []
    try:
        async for m in channel.history(limit=None, oldest_first=True):
            lines.append(f"[{m.created_at:%Y-%m-%d %H:%M}] {m.author}: {_message_text(m)}")
    except discord.HTTPException:
        lines.append("[не удалось прочитать историю канала]")
    data = "\n".join(lines) or "Сообщений нет."
    return discord.File(io.BytesIO(data.encode("utf-8")), filename=f"{channel.name}.txt")
