"""!canal - создаёт роли и каналы, которые нужны боту, и выдаёт их ID для .env.

- Существующие роли и каналы с такими же именами переиспользуются, дубли не создаются.
- Команду можно запускать повторно: уже созданное просто пропустится.
- Файл .env бот не трогает: он присылает готовый файл ids.env, который нужно вставить вручную.
"""
import io

import discord
from discord.ext import commands

from utils import clip, embed, is_admin_member

CATEGORY_NAME = "VOID | Управление"

# (ключ в .env, название роли)
ROLES = [
    ("ADMIN_ROLE_ID", "VOID Admin"),
    ("MEMBER_ROLE_ID", "VOID Member"),
    ("RECRUITER_ROLE_ID", "VOID Recruiter"),
    ("TIERCHECKER_ROLE_ID", "VOID Tier Checker"),
    ("MCL_ROLE_ID", "VOID MCL"),
    ("VACATION_ROLE_ID", "VOID Vacation"),
    ("AFK_ROLE_ID", "VOID AFK"),
    ("CAPT_BAN_ROLE_ID", "VOID CAPT Ban"),
    ("ROLE_TIER1_ID", "VOID CAPT Tier-1"),
    ("ROLE_TIER2_ID", "VOID CAPT Tier-2"),
    ("ROLE_MAIN_ID", "VOID CAPT Main"),
    ("ROLE_NEWBIE_ID", "VOID CAPT Newbie"),
]

# (ключ в .env, названия ролей по порядку; в .env пишется через запятую)
MULTI_ROLES = [
    ("TIER_ROLE_IDS", ["VOID Tier I", "VOID Tier II", "VOID Tier III"]),
    ("SUBDIVISION_ROLE_IDS", ["VOID Rec", "VOID Tch", "VOID High"]),
]

# (ключ в .env, название канала, доступ)
# open   - видят все, писать нельзя (заявки)
# staff  - видят только админы и бот (уведомления, откаты, лог)
CHANNELS = [
    ("APPLICATIONS_CHANNEL_ID", "заявки", "open"),
    ("NOTIFY_CHANNEL_ID", "уведомления", "staff"),
    ("ROLLBACK_CHANNEL_ID", "откаты", "staff"),
    ("LOG_CHANNEL_ID", "лог", "staff"),
]


def _find_role(guild: discord.Guild, name: str):
    return discord.utils.find(lambda r: r.name.lower() == name.lower(), guild.roles)


async def _ensure_role(guild: discord.Guild, name: str, created: list) -> discord.Role:
    role = _find_role(guild, name)
    if role is None:
        role = await guild.create_role(name=name, reason="!canal: настройка бота")
        created.append(name)
    return role


async def _ensure_category(guild: discord.Guild, created: list) -> discord.CategoryChannel:
    cat = discord.utils.get(guild.categories, name=CATEGORY_NAME)
    if cat is None:
        cat = await guild.create_category(CATEGORY_NAME, reason="!canal: настройка бота")
        created.append(CATEGORY_NAME)
    return cat


async def _ensure_channel(guild, category, name, access, admin_role, created):
    existing = discord.utils.get(guild.text_channels, name=name)
    if existing is not None:
        return existing

    # Бот всегда должен видеть свои каналы, иначе не сможет писать логи
    overwrites = {guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)}
    if access == "open":
        overwrites[guild.default_role] = discord.PermissionOverwrite(send_messages=False)
    else:
        overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
        overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

    ch = await guild.create_text_channel(
        name, category=category, overwrites=overwrites, reason="!canal: настройка бота"
    )
    created.append(f"#{name}")
    return ch


class Setup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="canal")
    @commands.guild_only()
    async def canal(self, ctx: commands.Context):
        """Создаёт роли и каналы для бота и выдаёт их ID для .env."""
        if not is_admin_member(ctx.author):
            return await ctx.send("Команда только для администраторов.")

        guild = ctx.guild
        me = guild.me
        if not (me.guild_permissions.manage_roles and me.guild_permissions.manage_channels):
            return await ctx.send("Боту нужны права **Manage Roles** и **Manage Channels**.")

        await ctx.send("⏳ Создаю роли и каналы, это займёт несколько секунд...")

        created: list[str] = []
        ids: dict[str, str] = {}
        error = None
        try:
            for key, name in ROLES:
                ids[key] = str((await _ensure_role(guild, name, created)).id)
            for key, names in MULTI_ROLES:
                ids[key] = ",".join(
                    str((await _ensure_role(guild, n, created)).id) for n in names
                )

            admin_role = guild.get_role(int(ids["ADMIN_ROLE_ID"]))
            category = await _ensure_category(guild, created)
            for key, name, access in CHANNELS:
                ch = await _ensure_channel(guild, category, name, access, admin_role, created)
                ids[key] = str(ch.id)
        except discord.HTTPException as e:
            error = str(e)

        env_text = "\n".join(f"{k}={v}" for k, v in ids.items())
        desc = [
            f"Создано: **{len(created)}**" if created else "Всё уже было создано ранее.",
        ]
        if created:
            desc.append(clip(", ".join(created), 1000))
        if error:
            desc.append(f"⚠️ Ошибка, часть не создана: `{error}`. Запустите `!canal` ещё раз.")
        desc.append("Скопируйте файл `ids.env` в `.env` и перезапустите бота.")

        await ctx.send(
            embed=embed("Настройка VOID", "\n".join(desc),
                        color=0xFF5555 if error else 0x2ECC71),
            file=discord.File(
                io.BytesIO(f"# Вставьте в .env\n{env_text}\n".encode("utf-8")),
                filename="ids.env",
            ),
        )


async def setup(bot):
    await bot.add_cog(Setup(bot))
