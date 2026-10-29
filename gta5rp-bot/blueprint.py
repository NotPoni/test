"""Схема сервера: роли, категории, каналы и права. Её создаёт и использует !setup."""
import discord

import config

STAFF_KEYS = ("role_owner", "role_dep_owner", "role_high", "role_recruiter")
HEAD_KEYS = ("role_owner", "role_dep_owner", "role_high")
MEMBER_KEYS = ("role_tier1", "role_tier2", "role_main", "role_newbie", "role_family")
TIER_KEYS = ("role_newbie", "role_main", "role_tier2", "role_tier1")  # от низшего к высшему

# ---------------------------------------------------------------- РОЛИ
# порядок = сверху вниз в иерархии
ROLES = [
    dict(key="role_owner", name=config.env_name("ROLE_OWNER", "𝙊𝙬𝙣𝙚𝙧👑"), color=0xF1C40F, hoist=True,
         env=["ROLE_OWNER_ID"], perms=dict(manage_roles=True, manage_channels=True, manage_messages=True,
                                           kick_members=True, ban_members=True, moderate_members=True,
                                           view_audit_log=True, mention_everyone=True)),
    dict(key="role_dep_owner", name=config.env_name("ROLE_DEP_OWNER", "𝘿𝙚𝙥.O𝙬𝙣𝙚𝙧⭐"), color=0xE67E22, hoist=True,
         env=["ROLE_DEP_OWNER_ID"], perms=dict(manage_roles=True, manage_messages=True, kick_members=True,
                                               ban_members=True, moderate_members=True, mention_everyone=True)),
    dict(key="role_high", name=config.env_name("ROLE_HIGH", "High 🔱"), color=0xE74C3C, hoist=True,
         env=["ROLE_HIGH_ID"], perms=dict(manage_messages=True, kick_members=True, moderate_members=True,
                                          mention_everyone=True)),
    dict(key="role_recruiter", name=config.env_name("ROLE_RECRUITER_NAME", "Recruiter 🎯"), color=0x3498DB,
         hoist=True, mentionable=True, env=["ROLE_RECRUITER_ID"],
         perms=dict(manage_messages=True, moderate_members=True, move_members=True)),
    dict(key="role_tier1", name="Tier-1", color=0x9B59B6, hoist=True, env=["ROLE_TIER1_ID"], perms={}),
    dict(key="role_tier2", name="Tier-2", color=0x8E44AD, hoist=True, env=["ROLE_TIER2_ID"], perms={}),
    dict(key="role_main", name="Main", color=0x2ECC71, hoist=True, env=["ROLE_MAIN_ID"], perms={}),
    dict(key="role_newbie", name="Newbie", color=0x95A5A6, hoist=True, env=["ROLE_NEWBIE_ID"], perms={}),
    dict(key="role_family", name=config.FAMILY_NAME, color=0x8B5CF6, hoist=False, mentionable=True,
         env=["ROLE_FAMILY_ID", "ROLE_TALENTLESS_ID"], perms={}),
    dict(key="role_applicant", name=config.env_name("ROLE_APPLICANT", "Подал заявку"), color=0xF39C12,
         env=["ROLE_APPLICANT_ID"], perms={}),
    dict(key="role_afk", name="AFK", color=0x7F8C8D, env=["ROLE_AFK_ID"], perms={}),
    dict(key="role_inactive", name="Инактив", color=0x5D6D7E, env=["ROLE_INACTIVE_ID"], perms={}),
    dict(key="role_donor", name="Donor 💎", color=0x1ABC9C, env=["ROLE_DONOR_ID"], perms={}),
    # бустер-роль создаёт сам Discord — бот её только привязывает
    dict(key="role_booster", name="Server Booster", color=0xF47FFF, env=["ROLE_BOOSTER_ID"], perms={}, create=False),
]


# ---------------------------------------------------------------- КАНАЛЫ
def categories() -> list[dict]:
    call_channels = [
        dict(key=f"vc_call_{i}", name=name, kind="voice")
        for i, name in enumerate(config.VOICE_CALL_CHANNELS, start=1)
    ]
    return [
        dict(name="📌 ИНФОРМАЦИЯ", access="public_ro", channels=[
            dict(key="ch_rules", name="📜・правила", panel="General"),
            dict(key="ch_news", name="📢・новости"),
            dict(key="ch_welcome", name="👋・приветствие"),
            dict(key="ch_apply", name="📝・подать-заявку", panel="Applications"),
            dict(key="ch_support", name="🆘・поддержка", panel="Tickets"),
        ]),
        dict(name="🎯 CAPT", access="members_ro", channels=[
            dict(key="ch_capt", name="🎯・capt", env=["CAPT_CHANNEL_ID"], access="members_ro_threads"),
            dict(name="🔊 Капт 1", kind="voice", access="members"),
            dict(name="🔊 Капт 2", kind="voice", access="members"),
        ]),
        dict(name="🏠 СЕМЬЯ", access="members", channels=[
            dict(name="💬・общий-чат"),
            dict(key="ch_afk", name="⏳・инактив", access="members_ro", panel="AFK"),
            dict(key="ch_warns", name="⚠️・варны", access="members_ro"),
            dict(key="ch_shifts", name="⏱️・смены", access="members_ro", panel="Shifts"),
            dict(key="ch_shop", name="🏆・баллы-и-магазин", access="members_ro", panel="Points"),
            dict(key="ch_cabinet", name="📁・создать-кабинет", access="members_ro", panel="Cabinets"),
            dict(name="🔊 Общий 1", kind="voice"),
            dict(name="🔊 Общий 2", kind="voice"),
            dict(key="vc_afk", name="😴 AFK", kind="voice"),
        ]),
        dict(name="🔊 ОБЗВОН", access="call", channels=call_channels),
        dict(key="cat_tickets", name=config.TICKETS_CATEGORY_NAME, access="staff", channels=[]),
        dict(key="cat_cabinets", name="📁 Личные кабинеты", access="staff", channels=[]),
        dict(name="🔒 ШТАБ", access="staff", channels=[
            dict(key="ch_log_apps", name="📥・лог-заявок"),
            dict(key="ch_hr", name="🧾・кадры"),
            dict(name="💬・штаб-чат"),
            dict(name="🔊 Штаб", kind="voice"),
        ]),
        dict(name="📜 ЛОГИ", access="staff", channels=[
            dict(key="ch_log", name="📜・общие-логи", env=["LOG_CHANNEL_ID"]),
            dict(key="ch_log_capt", name="🎯・логи-capt", env=["LOG_CAPT_CHANNEL_ID"]),
            dict(key="ch_log_voice", name="🔊・логи-голоса", env=["LOG_VOICE_CHANNEL_ID"]),
            dict(key="ch_log_afk", name="🕒・логи-afk", env=["AFK_LOG_CHANNEL_ID"]),
            dict(key="ch_log_shop", name="🛒・логи-магазина"),
        ]),
    ]


def norm_name(name: str, kind: str) -> str:
    """Discord приводит имена текстовых каналов к нижнему регистру и меняет пробелы на дефисы."""
    return name.lower().replace(" ", "-") if kind == "text" else name


# ---------------------------------------------------------------- ПРАВА
def build_overwrites(guild: discord.Guild, access: str, kind: str, roles: dict) -> dict:
    voice = kind == "voice"
    if voice and access.endswith("_ro"):
        access = access[:-3]

    def pick(keys):
        return [roles[k] for k in keys if roles.get(k)]

    staff, head = pick(STAFF_KEYS), pick(HEAD_KEYS)
    members = pick(MEMBER_KEYS)

    def allow():
        if voice:
            return discord.PermissionOverwrite(view_channel=True, connect=True, speak=True, stream=True)
        return discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                           attach_files=True, embed_links=True, add_reactions=True)

    def read_only(threads=False):
        return discord.PermissionOverwrite(view_channel=True, read_message_history=True, add_reactions=True,
                                           send_messages=False, create_public_threads=False,
                                           create_private_threads=False, send_messages_in_threads=threads)

    hidden = discord.PermissionOverwrite(view_channel=False)
    ow: dict = {guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True,
                                                      read_message_history=True, connect=True)}
    ev = guild.default_role

    if access == "public":
        ow[ev] = allow()
    elif access == "public_ro":
        ow[ev] = read_only()
        for r in staff:
            ow[r] = allow()
    elif access == "members":
        ow[ev] = hidden
        for r in members + staff:
            ow[r] = allow()
    elif access == "members_ro":
        ow[ev] = hidden
        for r in members:
            ow[r] = read_only()
        for r in staff:
            ow[r] = allow()
    elif access == "members_ro_threads":
        ow[ev] = hidden
        for r in members:
            ow[r] = read_only(True)
        for r in staff:
            ow[r] = allow()
    elif access == "staff":
        ow[ev] = hidden
        for r in staff:
            ow[r] = allow()
    elif access == "head":
        ow[ev] = hidden
        for r in head:
            ow[r] = allow()
    elif access == "call":
        ow[ev] = hidden
        for r in staff + pick(("role_applicant",)):
            ow[r] = allow()
    return ow
