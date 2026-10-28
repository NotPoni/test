import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from cogs.warns import take_warn
from utils import FieldsModal, admin_only, deny, embed, is_admin_member, parse_id, set_role, to_int


async def balance(db, uid):
    r = await db.one("SELECT balance FROM points WHERE user_id=?", uid)
    return r["balance"] if r else 0


async def spend(db, uid, amount):
    cur = await db.run("UPDATE points SET balance=balance-? WHERE user_id=? AND balance>=?", amount, uid, amount)
    return cur.rowcount > 0


class ShopView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Баланс", custom_id="sh:bal", style=discord.ButtonStyle.secondary)
    async def bal(self, i, _):
        await i.response.send_message(f"Ваш баланс: **{await balance(i.client.db, i.user.id)}** баллов.", ephemeral=True)

    @discord.ui.button(label="Товары", custom_id="sh:items", style=discord.ButtonStyle.primary)
    async def items(self, i, _):
        db = i.client.db
        rows = await db.all("SELECT * FROM shop_items WHERE enabled=1 LIMIT 25")
        if not rows:
            return await deny(i, "Товаров пока нет.")
        v = discord.ui.View(timeout=120)
        sel = discord.ui.Select(placeholder="Выберите товар", options=[
            discord.SelectOption(label=f"{r['name']} — {r['price']}"[:100], value=str(r["id"])) for r in rows])

        async def cb(inter):
            it = await db.one("SELECT * FROM shop_items WHERE id=? AND enabled=1", int(sel.values[0]))
            if not it:
                return await deny(inter, "Товар недоступен.")
            if not await spend(db, inter.user.id, it["price"]):
                return await deny(inter, "Недостаточно баллов.")
            await set_role(inter.user, it["role_id"])
            await inter.response.send_message(f"Куплено: **{it['name']}**.", ephemeral=True)

        sel.callback = cb
        v.add_item(sel)
        await i.response.send_message("Магазин:", view=v, ephemeral=True)

    @discord.ui.button(label="Рулетка", custom_id="sh:roulette", style=discord.ButtonStyle.success)
    async def roulette(self, i, _):
        db = i.client.db
        if await db.get("roulette_on", "0") != "1":
            return await deny(i, "Рулетка отключена.")
        rewards = await db.all("SELECT * FROM roulette_rewards")
        if not rewards:
            return await deny(i, "Награды рулетки не настроены.")
        price = int(await db.get("roulette_price", "100"))
        if not await spend(db, i.user.id, price):
            return await deny(i, f"Нужно {price} баллов.")
        win = random.choices(rewards, weights=[r["weight"] for r in rewards])[0]
        if win["points"]:
            await db.add_points(i.user.id, win["points"])
        await db.run("INSERT INTO roulette_history VALUES(?,?,?,?)", i.user.id, win["label"], win["points"], time.time())
        await i.response.send_message(
            embed=embed("🎰 Рулетка", f"Выпало: **{win['label']}** (+{win['points']} баллов)"), ephemeral=True)

    @discord.ui.button(label="Снять выговор", custom_id="sh:warn", style=discord.ButtonStyle.secondary)
    async def warn(self, i, _):
        db = i.client.db
        price = int(await db.get("warn_price", "500"))
        if not await db.one("SELECT 1 FROM warns WHERE user_id=?", i.user.id):
            return await deny(i, "У вас нет выговоров.")
        if not await spend(db, i.user.id, price):
            return await deny(i, f"Нужно {price} баллов.")
        lvl = await take_warn(i.client, i.guild, i.user.id)
        await i.response.send_message(f"Выговор снят. Осталось: {lvl}/3.", ephemeral=True)

    @discord.ui.button(label="Топ", custom_id="sh:top", style=discord.ButtonStyle.secondary)
    async def top(self, i, _):
        rows = await i.client.db.all("SELECT * FROM points ORDER BY balance DESC LIMIT 10")
        text = "\n".join(f"{n}. <@{r['user_id']}> — {r['balance']}" for n, r in enumerate(rows, 1)) or "Пусто."
        await i.response.send_message(embed=embed("Топ по баллам", text), ephemeral=True)


ADMIN = {
    "item_add": ("Новый товар", [("name", "Название"), ("price", "Цена"), ("role", "ID выдаваемой роли (0 = нет)")]),
    "item_del": ("Удалить товар", [("id", "ID товара")]),
    "item_toggle": ("Вкл/выкл товар", [("id", "ID товара")]),
    "points": ("Баллы участника", [("user", "ID или @упоминание"), ("delta", "Изменение: +100 / -50")]),
    "farm": ("Фарм баллов", [("rate", "Баллов за минуту в войсе")]),
    "warn_price": ("Цена снятия выговора", [("price", "Цена в баллах")]),
    "roulette_price": ("Цена прокрута", [("price", "Цена в баллах")]),
    "reward_add": ("Награда рулетки", [("label", "Название"), ("points", "Баллов"), ("weight", "Вес (шанс)")]),
}
ADMIN_OPTIONS = [
    ("Товар: добавить", "item_add"), ("Товар: удалить", "item_del"), ("Товар: вкл/выкл", "item_toggle"),
    ("Баллы: начислить/списать", "points"), ("Фарм: баллов в минуту", "farm"),
    ("Выговоры: цена снятия", "warn_price"), ("Рулетка: вкл/выкл", "roulette_toggle"),
    ("Рулетка: цена прокрута", "roulette_price"), ("Рулетка: добавить награду", "reward_add"),
    ("Рулетка: очистить награды", "reward_clear"),
]


async def admin_embed(db):
    items = await db.all("SELECT * FROM shop_items")
    rewards = await db.all("SELECT * FROM roulette_rewards")
    e = embed("Управление магазином", "Панель администратора: товары, баллы, фарм, выговоры, рулетка.")
    e.add_field(name="Фарм", value=f"{await db.get('farm_rate', '1')} балл/мин в войсе")
    e.add_field(name="Снятие выговора", value=f"{await db.get('warn_price', '500')} баллов")
    e.add_field(name="Рулетка", value=f"{'🟢' if await db.get('roulette_on', '0') == '1' else '🔴'} "
                                      f"цена {await db.get('roulette_price', '100')}")
    e.add_field(name="Товары", value="\n".join(
        f"#{r['id']} {r['name']} — {r['price']} {'✅' if r['enabled'] else '⏸'}" for r in items)[:1000] or "—", inline=False)
    e.add_field(name="Награды рулетки", value="\n".join(
        f"{r['label']}: +{r['points']} (вес {r['weight']})" for r in rewards)[:1000] or "—", inline=False)
    return e


async def apply(i, key, f):
    db = i.client.db
    bad = lambda: i.response.send_message("Неверные значения.", ephemeral=True)  # noqa: E731
    if key == "item_add":
        price, role = to_int(f["price"]), to_int(f["role"])
        if price is None or price < 0 or role is None:
            return await bad()
        await db.run("INSERT INTO shop_items(name,price,role_id) VALUES(?,?,?)", f["name"], price, role)
    elif key == "item_del":
        await db.run("DELETE FROM shop_items WHERE id=?", to_int(f["id"]))
    elif key == "item_toggle":
        await db.run("UPDATE shop_items SET enabled=1-enabled WHERE id=?", to_int(f["id"]))
    elif key == "points":
        uid, delta = parse_id(f["user"]), to_int(f["delta"])
        if not uid or delta is None:
            return await bad()
        await db.add_points(uid, delta)
    elif key in ("farm", "warn_price", "roulette_price"):
        n = to_int(f.get("rate") or f.get("price"))
        if n is None or n < 0:
            return await bad()
        await db.put({"farm": "farm_rate", "warn_price": "warn_price", "roulette_price": "roulette_price"}[key], n)
    elif key == "reward_add":
        pts, w = to_int(f["points"]), to_int(f["weight"])
        if pts is None or pts < 0 or not w or w < 1:
            return await bad()
        await db.run("INSERT INTO roulette_rewards(label,points,weight) VALUES(?,?,?)", f["label"], pts, w)
    await i.response.edit_message(embed=await admin_embed(db))


class ShopAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(custom_id="shadm:act", placeholder="Выберите действие",
                       options=[discord.SelectOption(label=l, value=v) for l, v in ADMIN_OPTIONS])
    async def act(self, i: discord.Interaction, sel: discord.ui.Select):
        if not is_admin_member(i.user):
            return await deny(i)
        key, db = sel.values[0], i.client.db
        if key == "roulette_toggle":
            await db.put("roulette_on", "0" if await db.get("roulette_on", "0") == "1" else "1")
            return await i.response.edit_message(embed=await admin_embed(db))
        if key == "reward_clear":
            await db.run("DELETE FROM roulette_rewards")
            return await i.response.edit_message(embed=await admin_embed(db))
        title, fields = ADMIN[key]

        async def done(inter, f):
            await apply(inter, key, f)

        await i.response.send_modal(FieldsModal(title, fields, done))


class Shop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(ShopView())
        self.bot.add_view(ShopAdminView())

    @app_commands.command(name="panel_shop", description="Магазин баллов (для участников)")
    @admin_only()
    async def shop(self, i: discord.Interaction):
        e = embed("Магазин", "Баллы начисляются за время в голосовых каналах. Покупки, рулетка, снятие выговора.")
        await i.response.send_message(embed=e, view=ShopView())

    @app_commands.command(name="panel_shop_admin", description="Управление магазином")
    @admin_only()
    async def shop_admin(self, i: discord.Interaction):
        await i.response.send_message(embed=await admin_embed(self.bot.db), view=ShopAdminView())


async def setup(bot):
    await bot.add_cog(Shop(bot))
