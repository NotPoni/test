import discord

import config

DIV = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"

MAX_TITLE = 256
MAX_DESCRIPTION = 4096
MAX_FIELD = 1024


def cut(text: str | None, limit: int) -> str | None:
    """Обрезает текст до лимита Discord, не оставляя «висящих» символов."""
    if text is None:
        return None
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def make(title=None, description=None, *, color=None, thumbnail=None, banner=False) -> discord.Embed:
    e = discord.Embed(
        title=cut(title, MAX_TITLE),
        description=cut(description, MAX_DESCRIPTION),
        color=color or config.COLOR_MAIN,
        timestamp=discord.utils.utcnow(),
    )
    e.set_footer(text=cut(config.BRAND, 2048), icon_url=_http(config.LOGO_URL))
    if thumbnail:
        e.set_thumbnail(url=_http(thumbnail))
    if banner and config.BANNER_URL:
        e.set_image(url=_http(config.BANNER_URL))
    return e


def _http(url: str | None) -> str | None:
    """Discord падает на невалидном icon_url — пропускаем всё, что не http(s)."""
    if url and url.startswith(("http://", "https://")):
        return url
    return None


def ok(text: str) -> discord.Embed:
    return make("✅ Готово", text, color=config.COLOR_OK)


def err(text: str) -> discord.Embed:
    return make("⛔ Ошибка", text, color=config.COLOR_ERR)


def fmt_time(seconds: int) -> str:
    seconds = max(0, int(seconds))
    d, rest = divmod(seconds, 86400)
    h, rest = divmod(rest, 3600)
    m = rest // 60
    parts = [f"{d}д" if d else "", f"{h}ч" if h else "", f"{m}м" if m else ""]
    return " ".join(p for p in parts if p) or "0м"


def fmt_minutes(minutes: int) -> str:
    d, rest = divmod(max(0, int(minutes)), 1440)
    h, m = divmod(rest, 60)
    parts = [f"{d}д" if d else "", f"{h}ч" if h else "", f"{m}м" if m else ""]
    return " ".join(p for p in parts if p) or "0м"
