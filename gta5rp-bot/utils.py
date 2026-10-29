import re
from datetime import datetime, timedelta

import config


def parse_when(text: str | None) -> datetime | None:
    """'20:00' | '25.12 21:30' | '25.12.2026 21:30' → aware datetime в часовом поясе бота."""
    if not text:
        return None
    text = text.strip()
    now = datetime.now(config.TZ)
    for fmt in ("%H:%M", "%d.%m %H:%M", "%d.%m.%Y %H:%M"):
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if fmt == "%H:%M":
            dt = now.replace(hour=dt.hour, minute=dt.minute, second=0, microsecond=0)
            if dt <= now:
                dt += timedelta(days=1)
        elif fmt == "%d.%m %H:%M":
            dt = dt.replace(year=now.year, tzinfo=config.TZ)
            if dt < now - timedelta(days=1):
                dt = dt.replace(year=now.year + 1)
        else:
            dt = dt.replace(tzinfo=config.TZ)
        return dt
    return None


_DUR = re.compile(r"(\d+)\s*([dдhчmм]?)", re.I)


def parse_minutes(text: str) -> int | None:
    """'90', '30m', '2h', '1d', '1h30m', '2ч 15м' → минуты."""
    text = text.strip().lower()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    total, matched = 0, False
    for num, unit in _DUR.findall(text):
        matched = True
        n = int(num)
        if unit in ("d", "д"):
            total += n * 1440
        elif unit in ("h", "ч"):
            total += n * 60
        else:
            total += n
    return total if matched and total > 0 else None


def chunk(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]
