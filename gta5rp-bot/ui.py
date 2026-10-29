import discord

import config

DIV = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"


def make(title=None, description=None, *, color=None, thumbnail=None, banner=False) -> discord.Embed:
    e = discord.Embed(
        title=title,
        description=description,
        color=color or config.COLOR_MAIN,
        timestamp=discord.utils.utcnow(),
    )
    e.set_footer(text=config.BRAND, icon_url=config.LOGO_URL)
    if thumbnail:
        e.set_thumbnail(url=thumbnail)
    if banner and config.BANNER_URL:
        e.set_image(url=config.BANNER_URL)
    return e


def ok(text: str) -> discord.Embed:
    return make("✅ Готово", text, color=config.COLOR_OK)


def err(text: str) -> discord.Embed:
    return make("⛔ Ошибка", text, color=config.COLOR_ERR)


def fmt_time(seconds: int) -> str:
    h, rest = divmod(int(seconds), 3600)
    return f"{h}ч {rest // 60}м"


def fmt_minutes(minutes: int) -> str:
    d, rest = divmod(int(minutes), 1440)
    h, m = divmod(rest, 60)
    parts = [f"{d}д" if d else "", f"{h}ч" if h else "", f"{m}м" if m else ""]
    return " ".join(p for p in parts if p) or "0м"
