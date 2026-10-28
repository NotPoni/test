import re

import discord
from discord import app_commands

from config import cfg


def has_any_role(m, *role_ids) -> bool:
    return isinstance(m, discord.Member) and any(r and m.get_role(r) for r in role_ids)


def is_admin_member(m) -> bool:
    return isinstance(m, discord.Member) and (
        m.guild_permissions.administrator or has_any_role(m, cfg.admin_role_id)
    )


def is_staff(m) -> bool:
    return is_admin_member(m) or has_any_role(m, cfg.recruiter_role_id, cfg.tierchecker_role_id)


def admin_only():
    async def pred(i: discord.Interaction) -> bool:
        return is_admin_member(i.user)
    return app_commands.check(pred)


def embed(title, desc="", color=0x7B2CFF):
    return discord.Embed(title=title, description=desc or None, color=color)


def clip(s, n=3900):
    return s if len(s) <= n else s[: n - 1] + "…"


def fmt_dur(sec):
    h, r = divmod(int(sec), 3600)
    return f"{h}ч {r // 60}м"


def parse_id(s):
    d = re.sub(r"\D", "", s or "")
    return int(d) if d else None


def to_int(s):
    try:
        return int(str(s).strip().replace("+", ""))
    except ValueError:
        return None


async def deny(i, text="Нет доступа."):
    if i.response.is_done():
        await i.followup.send(text, ephemeral=True)
    else:
        await i.response.send_message(text, ephemeral=True)


async def send_to(bot, channel_id, **kw):
    ch = bot.get_channel(channel_id) if channel_id else None
    if ch is None:
        return None
    try:
        return await ch.send(**kw)
    except discord.HTTPException:
        return None


async def set_role(member, role_id, add=True):
    role = member.guild.get_role(role_id) if role_id else None
    if role is None:
        return
    try:
        if add:
            await member.add_roles(role)
        else:
            await member.remove_roles(role)
    except discord.HTTPException:
        pass


class FieldsModal(discord.ui.Modal):
    """Универсальная форма: fields = [(key, label), ...] (до 5 полей)."""

    def __init__(self, title, fields, on_done):
        super().__init__(title=title[:45])
        self._on_done = on_done
        self._inputs = {}
        for key, label in fields:
            ti = discord.ui.TextInput(label=label[:45], max_length=300)
            self._inputs[key] = ti
            self.add_item(ti)

    async def on_submit(self, interaction):
        await self._on_done(interaction, {k: t.value.strip() for k, t in self._inputs.items()})
