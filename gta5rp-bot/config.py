import os
from datetime import timedelta, timezone

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int = 0) -> int:
    try:
        return int((os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float((os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


def _ids(name: str) -> list[int]:
    out = []
    for x in (os.getenv(name) or "").split(","):
        x = x.strip()
        if x.isdigit() and int(x):
            out.append(int(x))
    return out


def env_name(name: str, default: str) -> str:
    return (os.getenv(name) or "").strip() or default


TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = _int("GUILD_ID") or None
BRAND = env_name("BRAND", "GTA 5RP")
STATUS = env_name("STATUS", "GTA 5RP • !setup • /помощь")
FAMILY_NAME = env_name("FAMILY_NAME", "Talentless Clxn")
LOGO_URL = (os.getenv("LOGO_URL") or "").strip() or None
BANNER_URL = (os.getenv("BANNER_URL") or "").strip() or None
TZ = timezone(timedelta(hours=_int("TZ_OFFSET", 3)))
WHITELIST = set(_ids("WHITELIST"))

# роли с полным доступом (как REQUIRED_ROLES в старом боте)
STAFF_EXTRA_ROLE_IDS = _ids("REQUIRED_ROLES")

TICKETS_CATEGORY_NAME = env_name("TICKETS_CATEGORY_NAME", "🎫 Tickets")
VOICE_CALL_CHANNELS = [x.strip() for x in env_name("VOICE_CHANNELS", "🔊Обзвон 1,🔊Обзвон 2").split(",") if x.strip()]

# баллы
AP_PER_INTERVAL = _float("AP_PER_INTERVAL", 0.5)
INTERVAL_SECONDS = max(60, _int("INTERVAL_SECONDS", 1800))
MIN_USERS_IN_VOICE = _int("MIN_USERS_IN_VOICE", 2)
REWARDS = {"capt": _float("CAPT_REWARD", 2.0)}
EVENT_MAX_TOTAL = _int("EVENT_MAX_TOTAL", 99)

# палитра
COLOR_MAIN = 0x8B5CF6
COLOR_OK = 0x2ECC71
COLOR_ERR = 0xED4245
COLOR_WARN = 0xF1C40F
COLOR_INFO = 0x3498DB

# минут в голосовом с выключенным звуком без статуса AFK до предупреждения (0 — выключить)
AFK_WARN_MINUTES = _int("AFK_WARN_MINUTES", 30)
