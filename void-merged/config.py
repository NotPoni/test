import os

from dotenv import load_dotenv

load_dotenv()


def _int(name, default=0):
    v = os.getenv(name, "").split("#")[0].strip()
    return int(v) if v else default


def _str(name, default=""):
    return os.getenv(name, default).split("#")[0].strip() or default


def _ids(name):
    raw = os.getenv(name, "").split("#")[0]
    return [int(x) for x in raw.replace(" ", "").split(",") if x]


class Cfg:
    # Основное
    token = _str("DISCORD_TOKEN")
    guild_id = _int("GUILD_ID")
    db_path = _str("DB_PATH", "void.db")
    timezone = _str("TIMEZONE", "Europe/Moscow")

    # HTTP health-сервер (нужен для хостингов вроде Render). PORT не задан = выключен.
    host = _str("HOST", "0.0.0.0")
    port = _int("PORT")

    # Роли
    admin_role_id = _int("ADMIN_ROLE_ID")
    member_role_id = _int("MEMBER_ROLE_ID")
    recruiter_role_id = _int("RECRUITER_ROLE_ID")
    tierchecker_role_id = _int("TIERCHECKER_ROLE_ID")
    tier_role_ids = _ids("TIER_ROLE_IDS")
    subdivision_role_ids = _ids("SUBDIVISION_ROLE_IDS")
    mcl_role_id = _int("MCL_ROLE_ID")
    vacation_role_id = _int("VACATION_ROLE_ID")
    afk_role_id = _int("AFK_ROLE_ID")
    capt_ban_role_id = _int("CAPT_BAN_ROLE_ID")

    # Роли для автоматического распределения в CAPT (по приоритету сверху вниз)
    capt_roles = [
        ("Tier-1", _int("ROLE_TIER1_ID")),
        ("Tier-2", _int("ROLE_TIER2_ID")),
        ("Main", _int("ROLE_MAIN_ID")),
        ("Newbie", _int("ROLE_NEWBIE_ID")),
    ]

    # Каналы
    applications_channel_id = _int("APPLICATIONS_CHANNEL_ID")
    notify_channel_id = _int("NOTIFY_CHANNEL_ID")
    rollback_channel_id = _int("ROLLBACK_CHANNEL_ID")
    log_channel_id = _int("LOG_CHANNEL_ID")


cfg = Cfg()
