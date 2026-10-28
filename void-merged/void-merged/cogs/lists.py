"""Списки записи CAPT и MCL.

Перенесено из bot.py и переработано:
- данные хранятся в БД, поэтому списки переживают перезапуск бота;
- в CAPT участник сам попадает в группу по своей роли (приоритет Tier-1 -> Newbie);
- если основной список заполнен, запись автоматически идёт в «Замену».
"""
import asyncio
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import cfg
from utils import BRAND, MUTED, deny, embed, is_staff, send_to

REPLACE = "Замена"
AUTO_CLOSE_AFTER = 12 * 3600  # список закрывается через 12 ч после старта

KINDS = {
    "capt": {
        "title": "CAPTURES!",
        "label": "CAPT",
        "groups": ["Tier-1", "Tier-2", "Main", "Newbie"],
        "emoji": {"Tier-1": "⭐", "Tier-2": "🌟", "Main": "👑", "Newbie": "🌱"},
        "default_limit": 35,
        "max_limit": 99,
    },
    "mcl": {
        "title": "MCL!",
        "label": "MCL",
        "groups": ["Основы", "Ветераны", "Новички"],
        "emoji": {"Основы": "⭐", "Ветераны": "🌟", "Новички": "🌱"},
        "default_limit": 99,
        "max_limit": 99,
    },
}

# Блокировка на каждое объявление: защищает от гонок при одновременных нажатиях
_locks = defaultdict(asyncio.Lock)


# ---------- время ----------

def now() -> datetime:
    return datetime.now(ZoneInfo(cfg.timezone))


def parse_start(text: str) -> datetime:
    """'19:30' -> ближайшее будущее время с таким часом (сегодня или завтра)."""
    hh, mm = (int(x) for x in text.strip().split(":"))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(text)
    n = now()
    t = n.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return t + timedelta(days=1) if t <= n else t


# ---------- состояние ----------

def state_of(row) -> dict:
    return {
        "kind": row["kind"],
        "title": row["title"],
        "starts_at": row["starts_at"],
        "limit": row["limit_n"],
        "image_url": row["image_url"],
        "closed": row["closed"],
        "author_id": row["author_id"],
        "author_name": row["author_name"],
        "data": json.loads(row["data"]),
    }


async def get_row(db, message_id):
    return await db.one("SELECT * FROM sign_lists WHERE message_id=?", message_id)


async def latest_open(db, channel_id):
    return await db.one(
        "SELECT * FROM sign_lists WHERE channel_id=? AND closed=0 ORDER BY id DESC LIMIT 1",
        channel_id,
    )


async def save(db, message_id, data):
    await db.run("UPDATE sign_lists SET data=? WHERE message_id=?", json.dumps(data), message_id)


def find_group(data, uid):
    for group, ids in data.items():
        if uid in ids:
            return group
    return None


def main_count(s) -> int:
    return sum(len(s["data"].get(g, [])) for g in KINDS[s["kind"]]["groups"])


def capt_auto_group(member: discord.Member) -> str:
    """Группа CAPT по роли участника. Без роли - самая низкая группа."""
    for group, role_id in cfg.capt_roles:
        if role_id and member.get_role(role_id):
            return group
    return KINDS["capt"]["groups"][-1]


# ---------- отрисовка ----------

def render(s) -> discord.Embed:
    kind = KINDS[s["kind"]]
    data = s["data"]
    ts = int(s["starts_at"])
    total = main_count(s)

    lines = [
        f"**Время:** <t:{ts}:t> · <t:{ts}:R>",
        "",
        f"**Основной список ({total}/{s['limit']})**",
    ]
    if total >= s["limit"]:
        lines[-1] += " 🔴 ЗАПОЛНЕН"

    for group in kind["groups"] + [REPLACE]:
        ids = data.get(group, [])
        if group == REPLACE and not ids:
            continue
        lines.append("")
        lines.append(f"**{kind['emoji'].get(group, '🔄')} {group} [{len(ids)}]**")
        if ids:
            lines.extend(f"{n}. <@{uid}>" for n, uid in enumerate(ids, 1))
        else:
            lines.append("Пусто")

    title = s["title"] + ("  🔒 закрыт" if s["closed"] else "")
    return embed(
        title,
        "\n".join(lines),
        MUTED if s["closed"] else BRAND,
        image=s["image_url"] or None,
        footer=f"Создал {s['author_name']}",
    )


async def refresh(bot, message_id):
    """Перерисовывает сообщение списка по данным из БД."""
    row = await get_row(bot.db, message_id)
    if row is None:
        return
    channel = bot.get_channel(row["channel_id"])
    if channel is None:
        return
    s = state_of(row)
    try:
        msg = await channel.fetch_message(message_id)
        await msg.edit(embed=render(s), view=None if s["closed"] else discord.utils.MISSING)
    except discord.HTTPException:
        pass


# ---------- операции со списком ----------

async def place(i: discord.Interaction, message_id: int, group: str):
    db = i.client.db
    async with _locks[message_id]:
        row = await get_row(db, message_id)
        if row is None or row["closed"]:
            return await deny(i, "Список закрыт.")
        s = state_of(row)
        if find_group(s["data"], i.user.id):
            return await deny(i, "Вы уже записаны. Сначала нажмите «Выйти».")

        target, note = group, ""
        if group != REPLACE and main_count(s) >= s["limit"]:
            target, note = REPLACE, " Основной список заполнен, вы в замене."
        s["data"].setdefault(target, []).append(i.user.id)
        await save(db, message_id, s["data"])

    await i.response.send_message(f"✅ Вы записаны: **{target}**.{note}", ephemeral=True)
    await refresh(i.client, message_id)


async def remove_user(db, message_id: int, uid: int) -> bool:
    async with _locks[message_id]:
        row = await get_row(db, message_id)
        if row is None or row["closed"]:
            return False
        s = state_of(row)
        group = find_group(s["data"], uid)
        if group is None:
            return False
        s["data"][group].remove(uid)
        await save(db, message_id, s["data"])
        return True


async def close_list(bot, message_id: int):
    async with _locks[message_id]:
        await bot.db.run("UPDATE sign_lists SET closed=1 WHERE message_id=?", message_id)
    await refresh(bot, message_id)


# ---------- интерфейс ----------

class GroupSelect(discord.ui.Select):
    def __init__(self, message_id: int, kind: str):
        options = [discord.SelectOption(label=g) for g in KINDS[kind]["groups"] + [REPLACE]]
        super().__init__(placeholder="Выберите группу", options=options)
        self.message_id = message_id

    async def callback(self, i: discord.Interaction):
        await place(i, self.message_id, self.values[0])


class GroupPickView(discord.ui.View):
    def __init__(self, message_id: int, kind: str):
        super().__init__(timeout=120)
        self.add_item(GroupSelect(message_id, kind))


class ListView(discord.ui.View):
    """Постоянная панель. custom_id фиксированы, поэтому одна регистрация работает
    для всех списков, в том числе созданных до перезапуска."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Записаться", emoji="✅", style=discord.ButtonStyle.success, custom_id="lst:join")
    async def join(self, i: discord.Interaction, _):
        row = await get_row(i.client.db, i.message.id)
        if row is None or row["closed"]:
            return await deny(i, "Список закрыт.")
        if find_group(state_of(row)["data"], i.user.id):
            return await deny(i, "Вы уже записаны. Сначала нажмите «Выйти».")
        if row["kind"] == "capt":
            return await place(i, i.message.id, capt_auto_group(i.user))
        await i.response.send_message(
            "Выберите группу:", view=GroupPickView(i.message.id, row["kind"]), ephemeral=True
        )

    @discord.ui.button(label="Замена", emoji="🔄", style=discord.ButtonStyle.primary, custom_id="lst:sub")
    async def sub(self, i: discord.Interaction, _):
        await place(i, i.message.id, REPLACE)

    @discord.ui.button(label="Выйти", style=discord.ButtonStyle.secondary, custom_id="lst:leave")
    async def leave(self, i: discord.Interaction, _):
        if not await remove_user(i.client.db, i.message.id, i.user.id):
            return await deny(i, "Вас нет в списке или список закрыт.")
        await i.response.send_message("Вы покинули список.", ephemeral=True)
        await refresh(i.client, i.message.id)

    @discord.ui.button(label="Закрыть", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="lst:close")
    async def close_btn(self, i: discord.Interaction, _):
        row = await get_row(i.client.db, i.message.id)
        if row is None:
            return await deny(i, "Список не найден.")
        if row["closed"]:
            return await deny(i, "Список уже закрыт.")
        if not (is_staff(i.user) or i.user.id == row["author_id"]):
            return await deny(i, "Закрыть список может создатель или штаб.")
        await i.response.send_message("🔒 Список закрыт.", ephemeral=True)
        await close_list(i.client, i.message.id)


def staff_only():
    async def pred(i: discord.Interaction) -> bool:
        return is_staff(i.user)
    return app_commands.check(pred)


class Lists(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(ListView())
        self.auto_close.start()

    async def cog_unload(self):
        self.auto_close.cancel()

    async def _create(self, i, kind, start, name, image, limit, ping):
        k = KINDS[kind]
        try:
            starts = parse_start(start)
        except ValueError:
            return await deny(i, "Укажите время в формате **ЧЧ:ММ**, например `19:30`.")
        if not 1 <= limit <= k["max_limit"]:
            return await deny(i, f"Лимит должен быть от 1 до {k['max_limit']}.")
        if image and not image.startswith(("http://", "https://")):
            return await deny(i, "Ссылка на картинку должна начинаться с http:// или https://")

        await i.response.defer(ephemeral=True)
        state = {
            "kind": kind,
            "title": name or k["title"],
            "starts_at": starts.timestamp(),
            "limit": limit,
            "image_url": image,
            "closed": 0,
            "author_id": i.user.id,
            "author_name": i.user.display_name,
            "data": {g: [] for g in k["groups"] + [REPLACE]},
        }
        msg = await i.channel.send(
            content="@everyone" if ping else None,
            embed=render(state),
            view=ListView(),
            allowed_mentions=discord.AllowedMentions(everyone=ping),
        )
        await self.bot.db.run(
            "INSERT INTO sign_lists(guild_id, channel_id, message_id, kind, title, image_url, "
            "limit_n, starts_at, author_id, author_name, data, created) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            i.guild_id, i.channel_id, msg.id, kind, state["title"], image,
            limit, state["starts_at"], i.user.id, state["author_name"],
            json.dumps(state["data"]), time.time(),
        )
        await i.followup.send(f"✅ {k['label']} создан.", ephemeral=True)
        await send_to(
            self.bot, cfg.log_channel_id,
            embed=embed(
                f"Создан {k['label']}",
                f"Канал: <#{i.channel_id}>\nВремя: <t:{int(state['starts_at'])}:t>\n"
                f"Лимит: {limit}\nСоздал: {i.user.mention}",
            ),
        )

    @app_commands.command(name="create-capt", description="Создать запись на CAPT")
    @staff_only()
    @app_commands.describe(
        start="Время начала ЧЧ:ММ",
        name="Название",
        image="Ссылка на картинку",
        limit="Лимит основного списка",
        ping="Упомянуть @everyone",
    )
    async def create_capt(self, i: discord.Interaction, start: str, name: str = "",
                          image: str = "", limit: int = 35, ping: bool = True):
        await self._create(i, "capt", start, name, image, limit, ping)

    @app_commands.command(name="create-mcl", description="Создать запись на MCL")
    @staff_only()
    @app_commands.describe(
        start="Время начала ЧЧ:ММ",
        name="Название",
        image="Ссылка на картинку",
        limit="Лимит основного списка",
        ping="Упомянуть @everyone",
    )
    async def create_mcl(self, i: discord.Interaction, start: str, name: str = "",
                         image: str = "", limit: int = 99, ping: bool = True):
        await self._create(i, "mcl", start, name, image, limit, ping)

    @app_commands.command(name="list-kick", description="Убрать участника из открытого списка в этом канале")
    @staff_only()
    @app_commands.describe(member="Участник")
    async def list_kick(self, i: discord.Interaction, member: discord.Member):
        row = await latest_open(self.bot.db, i.channel_id)
        if row is None:
            return await deny(i, "В этом канале нет открытых списков.")
        if not await remove_user(self.bot.db, row["message_id"], member.id):
            return await deny(i, f"{member.display_name} не записан в список.")
        await i.response.send_message(f"✅ {member.mention} удалён из списка.", ephemeral=True)
        await refresh(self.bot, row["message_id"])

    @app_commands.command(name="list-close", description="Закрыть открытый список в этом канале")
    @staff_only()
    async def list_close(self, i: discord.Interaction):
        row = await latest_open(self.bot.db, i.channel_id)
        if row is None:
            return await deny(i, "В этом канале нет открытых списков.")
        await close_list(self.bot, row["message_id"])
        await i.response.send_message("🔒 Список закрыт.", ephemeral=True)

    @tasks.loop(minutes=10)
    async def auto_close(self):
        cutoff = time.time() - AUTO_CLOSE_AFTER
        rows = await self.bot.db.all(
            "SELECT message_id FROM sign_lists WHERE closed=0 AND starts_at<?", cutoff
        )
        for r in rows:
            await close_list(self.bot, r["message_id"])

    @auto_close.before_loop
    async def _wait(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Lists(bot))
