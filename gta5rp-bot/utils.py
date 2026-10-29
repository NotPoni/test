import re
from datetime import datetime, timedelta

import config


def now() -> datetime:
    return datetime.now(config.TZ)


def parse_when(text: str | None) -> datetime | None:
    """'20:00' | '25.12 21:30' | '25.12.2026 21:30' → aware datetime в часовом поясе бота."""
    if not text:
        return None
    text = text.strip()
    cur = now()
    for fmt in ("%H:%M", "%d.%m %H:%M", "%d.%m.%Y %H:%M"):
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        try:
            if fmt == "%H:%M":
                dt = cur.replace(hour=dt.hour, minute=dt.minute, second=0, microsecond=0)
                if dt <= cur:
                    dt += timedelta(days=1)
            elif fmt == "%d.%m %H:%M":
                dt = dt.replace(year=cur.year, tzinfo=config.TZ)
                if dt < cur:  # дата уже прошла → ближайший следующий год
                    dt = dt.replace(year=cur.year + 1)
            else:
                dt = dt.replace(tzinfo=config.TZ)
        except ValueError:  # например 29.02 в невисокосный год
            return None
        return dt
    return None


_DUR = re.compile(r"(\d+(?:[.,]\d+)?)\s*(d|д|дн|day|days|h|ч|час|hour|hours|m|м|мин|min|minutes)?", re.I)
_DAYS = ("d", "д", "дн", "day", "days")
_HOURS = ("h", "ч", "час", "hour", "hours")


def parse_minutes(text: str | None) -> int | None:
    """'90', '30m', '2h', '1d', '1h30m', '2ч 15м' → минуты."""
    if not text:
        return None
    text = text.strip().lower()
    if not text:
        return None
    total, matched = 0.0, False
    for num, unit in _DUR.findall(text):
        matched = True
        n = float(num.replace(",", "."))
        if unit in _DAYS:
            total += n * 1440
        elif unit in _HOURS:
            total += n * 60
        else:
            total += n
    if not matched:
        return None
    minutes = int(round(total))
    return minutes if minutes > 0 else None


def chunk(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]
