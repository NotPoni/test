import asyncio
import logging
import time
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import ui
from checks import get_channel, get_role, head_only, is_staff, send_log

STREAK_BONUS = 5.0
log = logging.getLogger(__name__)


class ShopSelect(discord.ui.Select):
    def __init__(self, items):
        super().__init__(
            placeholder="Выберите товар для покупки",
            options=[discord.SelectOption(label=i["name"][:100], value=str(i["id"]),
                                          description=f"{i['price']:g} баллов"[:100]) for i in items[:25]])

    async def callback(self, interaction: discord.Interaction):
        await interaction.client.get_cog("Points").buy(interaction, int(self.values[0]))


class ShopPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Магазин", emoji="🛒", style=discord.ButtonStyle.primary, custom_id="shop:open")
    async def open(self, interaction: discord.Interaction, button: discord.ui.Button):
        items = await interaction.client.db.fetchall(
            "SELECT * FROM shop_items WHERE guild_id=? AND stock != 0 ORDER BY price", interaction.guild_id)
        if not items:
            return await interaction.response.send_message(embed=ui.make("🛒 Магазин", "Пока пусто."), ephemeral=True)
        text = "\n".join(f"`#{i['id']}` **{i['name']}** — **{i['price']:g}** б."
                         + (f"\n> {i['description']}" if i["description"] else "")
                         + (f" (осталось: {i['stock']})" if i["stock"] > 0 else "") for i in items)
        view = discord.ui.View(timeout=120)
        view.add_item(ShopSelect(items))
        await interaction.response.send_message(embed=ui.make("🛒 Магазин", text[:4000]), view=view, ephemeral=True)

    @discord.ui.button(label="Мой баланс", emoji="💰", style=discord.ButtonStyle.secondary, custom_id="shop:balance")
    async def balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=await interaction.client.get_cog("Points").balance_embed(interaction.guild, interaction.user), ephemeral=True)

    @discord.ui.button(label="Топ", emoji="🏆", style=discord.ButtonStyle.secondary, custom_id="shop:top")
    async def top(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=await interaction.client.get_cog("Points").top_embed(interaction.guild, 10), ephemeral=True)


class PurchaseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Выдано", emoji="✅", style=discord.ButtonStyle.success, custom_id="shop:done")
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await is_staff(interaction):
            return await interaction.response.send_message(embed=ui.err("Недостаточно прав."), ephemeral=True)
        cur = await interaction.client.db.execute(
            "UPDATE purchases SET status='done' WHERE message_id=? AND status='new'", interaction.message.id)
        if cur.rowcount == 0:
            return await interaction.response.send_message(embed=ui.err("Покупка уже закрыта."), ephemeral=True)
        emb = interaction.message.embeds[0].copy()
        emb.color = config.COLOR_OK
        emb.add_field(name="Статус", value=f"✅ Выдано • {interaction.user.mention}", inline=False)
        await interaction.response.edit_message(embed=emb, view=None)


class Points(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.day_seen: dict = {}
        self.lock = asyncio.Lock()

    async def cog_load(self):
        self.bot.add_view(ShopPanelView())
        self.bot.add_view(PurchaseView())
        self.voice_loop.start()

    def cog_unload(self):
        self.voice_loop.cancel()

    # ---------------------------------------------------------------- ядро
    async def add_points(self, guild_id, user_id, amount, mod_id=0, kind="MANUAL", reason="", *, commit=True, log_it=True):
        db = self.bot.db
        sql_points = ("INSERT INTO points(guild_id,user_id,points) VALUES(?,?,?) "
                      "ON CONFLICT(guild_id,user_id) DO UPDATE SET points=MAX(0, points+?)")
        sql_log = ("INSERT INTO points_log(guild_id,user_id,mod_id,amount,kind,reason,ts) "
                   "VALUES(?,?,?,?,?,?,?)")
        args_points = (guild_id, user_id, max(amount, 0), amount)
        args_log = (guild_id, user_id, mod_id, amount, kind, reason, int(time.time()))
        # commit=False — вызывающий сам фиксирует изменения (голосовой цикл, батчи)
        if commit:
            async with db.transaction():
                await db.conn.execute(sql_points, args_points)
                if log_it:
                    await db.conn.execute(sql_log, args_log)
        else:
            await db.conn.execute(sql_points, args_points)
            if log_it:
                await db.conn.execute(sql_log, args_log)

    async def get_row(self, guild_id, user_id):
        return await self.bot.db.fetchone("SELECT * FROM points WHERE guild_id=? AND user_id=?", guild_id, user_id)

    async def balance_embed(self, guild, member) -> discord.Embed:
        row = await self.get_row(guild.id, member.id)
        pts, sec, streak = (row["points"], row["voice_seconds"], row["streak"]) if row else (0, 0, 0)
        e = ui.make("💰 Баланс", thumbnail=member.display_avatar.url)
        e.add_field(name="Баллы", value=f"**{pts:.1f}**")
        e.add_field(name="В голосе", value=ui.fmt_time(sec))
        e.add_field(name="Стрик", value=f"{streak} дн.")
        return e

    async def top_embed(self, guild, limit) -> discord.Embed:
        rows = await self.bot.db.fetchall(
            "SELECT user_id,points FROM points WHERE guild_id=? AND points>0 ORDER BY points DESC LIMIT ?", guild.id, limit)
        medals = ["🥇", "🥈", "🥉"]
        text = "\n".join(f"{medals[i] if i < 3 else f'`{i + 1}.`'} <@{r['user_id']}> — **{r['points']:.1f}**"
                         for i, r in enumerate(rows)) or "Пока пусто."
        return ui.make("🏆 Топ по баллам", text)

    # ---------------------------------------------------------------- голос
    @tasks.loop(seconds=60)
    async def voice_loop(self):
        db = self.bot.db
        per_minute = config.AP_PER_INTERVAL * 60 / config.INTERVAL_SECONDS
        now = datetime.now(config.TZ)
        today, yesterday = now.strftime("%Y-%m-%d"), (now - timedelta(days=1)).strftime("%Y-%m-%d")
        bonus = []
        try:
            for guild in self.bot.guilds:
                try:
                    afk_id = await db.get_setting(guild.id, "vc_afk")
                    donor = await get_role(self.bot, guild, "role_donor")
                    booster = await get_role(self.bot, guild, "role_booster")
                    for vc in guild.voice_channels:
                        if vc.id == afk_id or vc == guild.afk_channel:
                            continue
                        humans = [m for m in vc.members if not m.bot]
                        if len(humans) < config.MIN_USERS_IN_VOICE:
                            continue
                        for m in humans:
                            vs = m.voice
                            if not vs or vs.self_deaf or vs.self_mute or vs.deaf or vs.mute:
                                continue
                            mult = 2 if donor and donor in m.roles else 1.5 if booster and booster in m.roles else 1
                            await self.add_points(guild.id, m.id, per_minute * mult, 0, "VOICE", commit=False, log_it=False)
                            await db.conn.execute(
                                "UPDATE points SET voice_seconds=voice_seconds+60 WHERE guild_id=? AND user_id=?",
                                (guild.id, m.id))
                            key = (guild.id, m.id)
                            if self.day_seen.get(key) != today:
                                row = await self.get_row(guild.id, m.id)
                                if row is not None and row["last_day"] != today:
                                    streak = row["streak"] + 1 if row["last_day"] == yesterday else 1
                                    await db.conn.execute(
                                        "UPDATE points SET streak=?, last_day=? WHERE guild_id=? AND user_id=?",
                                        (streak, today, guild.id, m.id))
                                    if streak % 7 == 0:
                                        await self.add_points(guild.id, m.id, STREAK_BONUS, 0, "STREAK", "Стрик 7 дней",
                                                              commit=False)
                                        bonus.append(m)
                                self.day_seen[key] = today
                except Exception:
                    log.exception("Ошибка начисления баллов (guild=%s)", guild.id)
        finally:
            # фиксируем всё, что успели начислить, даже если где-то упало
            try:
                await db.commit()
            except Exception:
                log.exception("Не удалось сохранить начисления баллов")
        for m in bonus:
            try:
                await m.send(f"🎉 Ты получил **{STREAK_BONUS:g}** баллов за недельный стрик в голосе!")
            except discord.HTTPException:
                pass

    @voice_loop.before_loop
    async def _wait(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot or before.channel == after.channel:
            return
        if before.channel is None:
            title, text, color = "🔵 Вход в голосовой", f"{member.mention} → **{after.channel.name}**", config.COLOR_OK
        elif after.channel is None:
            title, text, color = "🔴 Выход из голосового", f"{member.mention} ← **{before.channel.name}**", config.COLOR_ERR
        else:
            title, text, color = ("🔄 Перемещение",
                                  f"{member.mention}: **{before.channel.name}** → **{after.channel.name}**",
                                  config.COLOR_WARN)
        await send_log(self.bot, member.guild, ui.make(title, text, color=color), "ch_log_voice")

    # ---------------------------------------------------------------- панель
    async def post_panel(self, channel, key):
        e = ui.make("🏆 Баллы и магазин",
                    f"Баллы капают за **голосовой онлайн** (от {config.MIN_USERS_IN_VOICE} человек, без мута), "
                    f"за события и принятие заявки.\n{ui.DIV}\n"
                    f"• {config.AP_PER_INTERVAL:g} балла за {config.INTERVAL_SECONDS // 60} мин в голосе\n"
                    f"• CAPT **{config.REWARDS['capt']:g}** за участие в составе\n• Бустеры ×1.5, доноры ×2\n"
                    f"• 7 дней в голосе подряд — **+{STREAK_BONUS:g}**", banner=True)
        await channel.send(embed=e, view=ShopPanelView())

    # ---------------------------------------------------------------- покупки
    async def buy(self, interaction: discord.Interaction, item_id: int):
        g, user, db = interaction.guild, interaction.user, self.bot.db
        item, purchase_id, error = None, None, None
        async with self.lock:
            async with db.transaction():
                cur = await db.conn.execute(
                    "SELECT * FROM shop_items WHERE id=? AND guild_id=?", (item_id, g.id))
                item = await cur.fetchone()
                if item is None or item["stock"] == 0:
                    error = "❌ Товар недоступен."
                else:
                    price = item["price"]
                    cur = await db.conn.execute(
                        "UPDATE points SET points=points-? WHERE guild_id=? AND user_id=? AND points>=?",
                        (price, g.id, user.id, price))
                    if cur.rowcount == 0:
                        row = await (await db.conn.execute(
                            "SELECT points FROM points WHERE guild_id=? AND user_id=?", (g.id, user.id))).fetchone()
                        have = row["points"] if row else 0
                        error = f"❌ Не хватает баллов: нужно **{price:g}**, у вас **{have:.1f}**."
                    else:
                        await db.conn.execute(
                            "INSERT INTO points_log(guild_id,user_id,mod_id,amount,kind,reason,ts) "
                            "VALUES(?,?,?,?,?,?,?)",
                            (g.id, user.id, 0, -price, "SHOP", item["name"], int(time.time())))
                        if item["stock"] > 0:
                            await db.conn.execute(
                                "UPDATE shop_items SET stock=stock-1 WHERE id=? AND stock>0", (item_id,))
                        cur = await db.conn.execute(
                            "INSERT INTO purchases(guild_id,user_id,item_name,price,ts) VALUES(?,?,?,?,?)",
                            (g.id, user.id, item["name"], price, int(time.time())))
                        purchase_id = cur.lastrowid
        if error:
            return await interaction.response.edit_message(content=error, embed=None, view=None)

        e = ui.make("🛒 Новая покупка", color=config.COLOR_WARN, thumbnail=user.display_avatar.url)
        e.add_field(name="Покупатель", value=user.mention)
        e.add_field(name="Товар", value=item["name"])
        e.add_field(name="Цена", value=f"{item['price']:g} б.")
        ch = await get_channel(self.bot, g, "ch_log_shop")
        if ch:
            try:
                msg = await ch.send(embed=e, view=PurchaseView())
                await db.execute("UPDATE purchases SET message_id=? WHERE id=?", msg.id, purchase_id)
            except discord.HTTPException:
                pass
        await interaction.response.edit_message(
            content=f"✅ Куплено: **{item['name']}**. Руководство выдаст товар.", embed=None, view=None)

    # ---------------------------------------------------------------- команды
    @app_commands.command(name="баллы", description="Показать баланс баллов")
    @app_commands.guild_only()
    async def balance(self, interaction: discord.Interaction, member: discord.Member | None = None):
        await interaction.response.send_message(
            embed=await self.balance_embed(interaction.guild, member or interaction.user), ephemeral=True)

    @app_commands.command(name="топ", description="Топ по баллам")
    @app_commands.guild_only()
    async def top(self, interaction: discord.Interaction, limit: app_commands.Range[int, 3, 25] = 10):
        await interaction.response.send_message(embed=await self.top_embed(interaction.guild, limit))

    async def _adjust(self, interaction, member, amount, reason, title):
        await self.add_points(interaction.guild_id, member.id, amount, interaction.user.id, "MANUAL", reason)
        e = ui.make(title, color=config.COLOR_OK if amount > 0 else config.COLOR_WARN, thumbnail=member.display_avatar.url)
        e.add_field(name="Пользователь", value=member.mention)
        e.add_field(name="Баллы", value=f"{amount:+g}")
        e.add_field(name="Выдал", value=interaction.user.mention)
        e.add_field(name="Причина", value=ui.cut(reason, 1024), inline=False)
        await interaction.response.send_message(embed=e)
        await send_log(self.bot, interaction.guild, e)

    @app_commands.command(name="выдать_баллы", description="Выдать баллы пользователю")
    @app_commands.guild_only()
    @head_only()
    async def give(self, interaction: discord.Interaction, member: discord.Member,
                   amount: app_commands.Range[float, 0.1, 10000.0], reason: str):
        await self._adjust(interaction, member, amount, reason, "➕ Выдача баллов")

    @app_commands.command(name="забрать_баллы", description="Снять баллы у пользователя")
    @app_commands.guild_only()
    @head_only()
    async def take(self, interaction: discord.Interaction, member: discord.Member,
                   amount: app_commands.Range[float, 0.1, 10000.0], reason: str):
        await self._adjust(interaction, member, -amount, reason, "➖ Снятие баллов")

    @app_commands.command(name="обнулить_баллы", description="Обнулить баллы пользователя")
    @app_commands.guild_only()
    @head_only()
    async def reset_one(self, interaction: discord.Interaction, member: discord.Member, reason: str = "По решению руководства"):
        await self.bot.db.execute("UPDATE points SET points=0 WHERE guild_id=? AND user_id=?",
                                  interaction.guild_id, member.id)
        await interaction.response.send_message(embed=ui.ok(f"Баллы {member.mention} обнулены."))
        await send_log(self.bot, interaction.guild,
                       ui.make("♻️ Обнуление баллов",
                               f"{member.mention}\n{ui.cut(reason, 1024)}\n— {interaction.user.mention}",
                               color=config.COLOR_WARN))

    @app_commands.command(name="обнулить_все_баллы", description="Обнулить баллы ВСЕХ (введите ПОДТВЕРЖДАЮ)")
    @app_commands.guild_only()
    @head_only()
    async def reset_all(self, interaction: discord.Interaction, confirm: str):
        if confirm.strip().upper() != "ПОДТВЕРЖДАЮ":
            return await interaction.response.send_message(embed=ui.err("Введите слово `ПОДТВЕРЖДАЮ`."), ephemeral=True)
        await self.bot.db.execute("UPDATE points SET points=0 WHERE guild_id=?", interaction.guild_id)
        await interaction.response.send_message(embed=ui.ok("Баллы всех участников обнулены."))
        await send_log(self.bot, interaction.guild,
                       ui.make("♻️ Массовое обнуление баллов", f"Инициатор: {interaction.user.mention}",
                               color=config.COLOR_ERR))

    @app_commands.command(name="товар_добавить", description="Добавить товар в магазин")
    @app_commands.describe(stock="Количество (-1 = без ограничений)")
    @app_commands.guild_only()
    @head_only()
    async def item_add(self, interaction: discord.Interaction, name: str,
                       price: app_commands.Range[float, 0.1, 100000.0],
                       description: str = "", stock: int = -1):
        if stock < -1:
            return await interaction.response.send_message(embed=ui.err("stock должен быть ≥ -1."), ephemeral=True)
        await self.bot.db.execute("INSERT INTO shop_items(guild_id,name,price,description,stock) VALUES(?,?,?,?,?)",
                                  interaction.guild_id, name[:100], price, description[:200], stock)
        await interaction.response.send_message(embed=ui.ok(f"Товар **{name}** добавлен за {price:g} б."), ephemeral=True)

    @app_commands.command(name="товар_удалить", description="Удалить товар по номеру")
    @app_commands.guild_only()
    @head_only()
    async def item_del(self, interaction: discord.Interaction, item_id: int):
        await self.bot.db.execute("DELETE FROM shop_items WHERE id=? AND guild_id=?", item_id, interaction.guild_id)
        await interaction.response.send_message(embed=ui.ok(f"Товар #{item_id} удалён."), ephemeral=True)

    @app_commands.command(name="товары", description="Список товаров с номерами")
    @app_commands.guild_only()
    @head_only()
    async def items(self, interaction: discord.Interaction):
        rows = await self.bot.db.fetchall("SELECT * FROM shop_items WHERE guild_id=? ORDER BY id", interaction.guild_id)
        text = "\n".join(f"`#{r['id']}` **{r['name']}** — {r['price']:g} б. • остаток: "
                         f"{'∞' if r['stock'] < 0 else r['stock']}" for r in rows) or "Пусто."
        await interaction.response.send_message(embed=ui.make("🛒 Товары", text), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Points(bot))
