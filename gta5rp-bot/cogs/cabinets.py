import re

import discord
from discord.ext import commands

import config
import ui
from checks import get_channel, is_staff, staff_roles

THREADS = ["капт", "mcl", "gg", "рп-отчёты", "покупки-и-логи", "чат"]
IMG_EXT = (".gif", ".png", ".jpg", ".jpeg", ".webp")


def is_win(text: str) -> bool:
    t = text.strip().lower()
    return t.startswith(("поб", "win", "w", "+", "вин", "выиг"))


def rollback_value(url: str) -> str:
    return f"[▶️ Смотреть откат]({url})"


def capt_embed(row) -> discord.Embed:
    win = row["result"] == "win"
    e = ui.make(f"🎯 Капт #{row['id']}", color=config.COLOR_OK if win else config.COLOR_ERR)
    e.add_field(name="📅 Дата", value=row["date"])
    e.add_field(name="🏁 Итог", value="Победа" if win else "Поражение")
    e.add_field(name="\u200b", value="\u200b")
    e.add_field(name="🎯 Киллы", value=f"**{row['kills']}**")
    e.add_field(name="💥 Урон", value=f"**{row['damage']}**")
    if row["rollback"]:
        e.add_field(name="🎬 Откат", value=rollback_value(row["rollback"]), inline=False)
    return e


async def can_use(interaction: discord.Interaction, owner_id: int) -> bool:
    return interaction.user.id == owner_id or await is_staff(interaction)


class CreateModal(discord.ui.Modal, title="📁 Создание кабинета"):
    static = discord.ui.TextInput(label="Статический ID", placeholder="49951", max_length=10)
    server = discord.ui.TextInput(label="Сервер (цифры)", placeholder="18", max_length=5)
    video = discord.ui.TextInput(label="Ссылка на гифку/видео (необязательно)", required=False, max_length=300)

    async def on_submit(self, interaction: discord.Interaction):
        bot, g, db = interaction.client, interaction.guild, interaction.client.db
        if g is None:
            return await interaction.response.send_message(embed=ui.err("Только на сервере."), ephemeral=True)
        static, server = self.static.value.strip(), self.server.value.strip()
        video = self.video.value.strip()
        if not static.isdigit() or not server.isdigit():
            return await interaction.response.send_message(
                embed=ui.err("Статический ID и сервер — только цифры."), ephemeral=True)
        if video and not video.startswith(("http://", "https://")):
            return await interaction.response.send_message(
                embed=ui.err("Ссылка должна начинаться с http(s)://"), ephemeral=True)
        exists = await db.fetchone("SELECT channel_id FROM cabinets WHERE guild_id=? AND user_id=?", g.id, interaction.user.id)
        if exists and g.get_channel(exists["channel_id"]):
            return await interaction.response.send_message(
                embed=ui.err(f"У вас уже есть кабинет: <#{exists['channel_id']}>"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        category = await get_channel(bot, g, "cat_cabinets")
        if not isinstance(category, discord.CategoryChannel):
            category = await g.create_category("📁 Личные кабинеты", overwrites={
                g.default_role: discord.PermissionOverwrite(view_channel=False)})
            await db.set_setting(g.id, "cat_cabinets", category.id)

        perms = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                            attach_files=True, embed_links=True, create_public_threads=True,
                                            send_messages_in_threads=True)
        overwrites = {g.default_role: discord.PermissionOverwrite(view_channel=False), interaction.user: perms,
                      g.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)}
        for role in await staff_roles(bot, g):
            overwrites[role] = perms
        slug = re.sub(r"[^\w\-]+", "-", interaction.user.display_name.lower()).strip("-")[:30] or "user"
        try:
            channel = await g.create_text_channel(f"👤・{slug}-{static}", category=category,
                                                  overwrites=overwrites, topic=f"cabinet:{interaction.user.id}")
        except discord.HTTPException:
            return await interaction.followup.send(embed=ui.err("Не удалось создать канал кабинета."), ephemeral=True)
        await db.execute(
            "INSERT OR REPLACE INTO cabinets(guild_id,user_id,channel_id,static,server,video) VALUES(?,?,?,?,?,?)",
            g.id, interaction.user.id, channel.id, static, server, video)
        for name in THREADS:
            try:
                th = await channel.create_thread(name=name, type=discord.ChannelType.public_thread,
                                                 auto_archive_duration=10080)
                await db.execute("INSERT OR REPLACE INTO cabinet_threads(channel_id,name,thread_id) VALUES(?,?,?)",
                                 channel.id, name, th.id)
            except discord.HTTPException:
                pass
        cog = bot.get_cog("Cabinets")
        await cog.refresh(g, interaction.user)
        await interaction.followup.send(embed=ui.ok(f"Кабинет создан: {channel.mention}"), ephemeral=True)


class CaptModal(discord.ui.Modal, title="🎯 Добавить капт"):
    date = discord.ui.TextInput(label="Дата", placeholder="25.12", max_length=20)
    result = discord.ui.TextInput(label="Итог", placeholder="победа / поражение", max_length=20)
    kills = discord.ui.TextInput(label="Киллы", placeholder="12", max_length=3)
    damage = discord.ui.TextInput(label="Урон", placeholder="18500", max_length=6)
    rollback = discord.ui.TextInput(label="Ссылка на откат (необязательно)", required=False, max_length=300)

    def __init__(self, cab):
        super().__init__()
        self.cab = cab

    async def on_submit(self, interaction: discord.Interaction):
        if not (self.kills.value.isdigit() and self.damage.value.isdigit()):
            return await interaction.response.send_message(embed=ui.err("Киллы и урон — только числа."), ephemeral=True)
        url = self.rollback.value.strip()
        if url and not url.startswith(("http://", "https://")):
            return await interaction.response.send_message(embed=ui.err("Ссылка должна начинаться с http(s)://"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        bot, g, db = interaction.client, interaction.guild, interaction.client.db
        cur = await db.execute(
            "INSERT INTO cabinet_capts(guild_id,user_id,date,result,kills,damage,rollback) VALUES(?,?,?,?,?,?,?)",
            g.id, self.cab["user_id"], self.date.value.strip(), "win" if is_win(self.result.value) else "lose",
            int(self.kills.value), int(self.damage.value), url)
        row = await db.fetchone("SELECT * FROM cabinet_capts WHERE id=?", cur.lastrowid)
        th = await db.fetchone("SELECT thread_id FROM cabinet_threads WHERE channel_id=? AND name='капт'", self.cab["channel_id"])
        target = None
        if th:
            target = g.get_thread(th["thread_id"])
            if target is None:
                try:
                    target = await g.fetch_channel(th["thread_id"])
                except discord.HTTPException:
                    target = None
        target = target or g.get_channel(self.cab["channel_id"])
        if target is None:
            return await interaction.followup.send(embed=ui.err("Канал кабинета не найден."), ephemeral=True)
        try:
            msg = await target.send(embed=capt_embed(row))
        except discord.HTTPException:
            return await interaction.followup.send(embed=ui.err("Не удалось отправить капт в кабинет."), ephemeral=True)
        await db.execute("UPDATE cabinet_capts SET message_id=?, thread_id=? WHERE id=?", msg.id, target.id, row["id"])
        member = g.get_member(self.cab["user_id"])
        if member:
            await bot.get_cog("Cabinets").refresh(g, member)
        await interaction.followup.send(embed=ui.ok(f"Капт **#{row['id']}** добавлен."), ephemeral=True)


class RollbackModal(discord.ui.Modal, title="🎬 Добавить откат"):
    number = discord.ui.TextInput(label="Номер капта (#)", placeholder="5", max_length=8)
    url = discord.ui.TextInput(label="Ссылка на откат", placeholder="https://youtu.be/...", max_length=300)

    def __init__(self, cab):
        super().__init__()
        self.cab = cab

    async def on_submit(self, interaction: discord.Interaction):
        db, g = interaction.client.db, interaction.guild
        url = self.url.value.strip()
        if not self.number.value.isdigit() or not url.startswith(("http://", "https://")):
            return await interaction.response.send_message(embed=ui.err("Проверьте номер и ссылку (http/https)."), ephemeral=True)
        row = await db.fetchone("SELECT * FROM cabinet_capts WHERE id=? AND guild_id=?", int(self.number.value), g.id)
        if not row or not await can_use(interaction, row["user_id"]):
            return await interaction.response.send_message(embed=ui.err("Капт не найден или он не ваш."), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await db.execute("UPDATE cabinet_capts SET rollback=? WHERE id=?", url, row["id"])
        target = None
        if row["thread_id"]:
            target = g.get_thread(row["thread_id"])
            if target is None:
                try:
                    target = await g.fetch_channel(row["thread_id"])
                except discord.HTTPException:
                    target = None
        target = target or g.get_channel(self.cab["channel_id"])
        if target and row["message_id"]:
            try:
                msg = await target.fetch_message(row["message_id"])
                await msg.edit(embed=capt_embed(await db.fetchone("SELECT * FROM cabinet_capts WHERE id=?", row["id"])))
            except discord.HTTPException:
                pass
        await interaction.followup.send(embed=ui.ok("Откат добавлен."), ephemeral=True)


class CreateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Создать кабинет", emoji="📁", style=discord.ButtonStyle.primary, custom_id="cab:create")
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreateModal())


class CabinetView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _cab(self, interaction):
        if interaction.channel is None:
            await interaction.response.send_message(embed=ui.err("Это не ваш кабинет."), ephemeral=True)
            return None
        cab = await interaction.client.db.fetchone("SELECT * FROM cabinets WHERE channel_id=?", interaction.channel.id)
        if not cab:
            cab = await interaction.client.db.fetchone(
                "SELECT c.* FROM cabinets c JOIN cabinet_threads t ON t.channel_id=c.channel_id WHERE t.thread_id=?",
                interaction.channel.id)
        if not cab or not await can_use(interaction, cab["user_id"]):
            await interaction.response.send_message(embed=ui.err("Это не ваш кабинет."), ephemeral=True)
            return None
        return cab

    @discord.ui.button(label="Обновить", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="cab:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        cab = await self._cab(interaction)
        if not cab:
            return
        await interaction.response.defer(ephemeral=True)
        member = interaction.guild.get_member(cab["user_id"])
        if member:
            await interaction.client.get_cog("Cabinets").refresh(interaction.guild, member)
        await interaction.followup.send(embed=ui.ok("Обновлено."), ephemeral=True)

    @discord.ui.button(label="Добавить капт", emoji="🎯", style=discord.ButtonStyle.success, custom_id="cab:capt")
    async def add_capt(self, interaction: discord.Interaction, button: discord.ui.Button):
        cab = await self._cab(interaction)
        if cab:
            await interaction.response.send_modal(CaptModal(cab))

    @discord.ui.button(label="Добавить откат", emoji="🎬", style=discord.ButtonStyle.primary, custom_id="cab:rollback")
    async def add_rollback(self, interaction: discord.Interaction, button: discord.ui.Button):
        cab = await self._cab(interaction)
        if cab:
            await interaction.response.send_modal(RollbackModal(cab))


class Cabinets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(CreateView())
        self.bot.add_view(CabinetView())

    async def post_panel(self, channel, key):
        e = ui.make("📁 Личные кабинеты",
                    f"Личный канал с ветками **{', '.join(THREADS)}**, статистикой, баллами и откатами.\n{ui.DIV}\n"
                    "Нажмите кнопку и укажите Static ID и сервер.", banner=True)
        await channel.send(embed=e, view=CreateView())

    async def stats_embed(self, guild, member, cab) -> discord.Embed:
        db = self.bot.db
        e = ui.make(f"👤 Кабинет {member.display_name}", thumbnail=member.display_avatar.url)
        e.add_field(name="🏷️ Семья", value=f"`{config.FAMILY_NAME}`", inline=False)
        e.add_field(name="🆔 Static", value=f"`{cab['static']}`")
        e.add_field(name="🌐 Сервер", value=f"`{cab['server']}`")
        points = self.bot.get_cog("Points")
        row = await points.get_row(guild.id, member.id) if points else None
        e.add_field(name="💰 Баллы", value=f"**{row['points']:.1f}**" if row else "**0**")
        e.add_field(name="🎙️ В голосе", value=ui.fmt_time(row["voice_seconds"]) if row else "0ч 0м")
        e.add_field(name="🔥 Стрик", value=f"{row['streak']} дн." if row else "0 дн.")
        e.add_field(name="\u200b", value="\u200b")
        ev = await db.fetchall("SELECT kind, COUNT(*) c FROM events_log WHERE guild_id=? AND user_id=? GROUP BY kind",
                               guild.id, member.id)
        counts = {r["kind"]: r["c"] for r in ev}
        e.add_field(name="🗓️ Участия", value=f"CAPT **{counts.get('capt', 0)}**", inline=False)
        st = await db.fetchone(
            "SELECT COUNT(*) c, AVG(kills) k, AVG(damage) d, SUM(result='win') w FROM cabinet_capts "
            "WHERE guild_id=? AND user_id=?", guild.id, member.id)
        if st and st["c"]:
            e.add_field(name="🏆 Капты", value=f"**{st['c']}** сыграно")
            e.add_field(name="📈 Винрейт", value=f"**{(st['w'] or 0) / st['c'] * 100:.0f}%**")
            e.add_field(name="\u200b", value="\u200b")
            e.add_field(name="💥 Ср. урон", value=f"**{st['d']:.0f}**")
            e.add_field(name="☠️ Ср. киллы", value=f"**{st['k']:.2f}**")
        else:
            e.add_field(name="🏆 Капты", value="*пока нет записей — нажмите «Добавить капт»*", inline=False)
        if cab["video"]:
            if cab["video"].lower().split("?")[0].endswith(IMG_EXT):
                e.set_image(url=cab["video"])
            else:
                e.add_field(name="🎬 Видео", value=f"[Открыть]({cab['video']})", inline=False)
        return e

    async def refresh(self, guild: discord.Guild, member: discord.Member):
        db = self.bot.db
        cab = await db.fetchone("SELECT * FROM cabinets WHERE guild_id=? AND user_id=?", guild.id, member.id)
        if not cab:
            return
        channel = guild.get_channel(cab["channel_id"])
        if not channel:
            return
        embed = await self.stats_embed(guild, member, cab)
        if cab["info_msg"]:
            try:
                msg = await channel.fetch_message(cab["info_msg"])
                return await msg.edit(embed=embed, view=CabinetView())
            except discord.HTTPException:
                pass
        try:
            msg = await channel.send(embed=embed, view=CabinetView())
        except discord.HTTPException:
            return
        await db.execute("UPDATE cabinets SET info_msg=? WHERE guild_id=? AND user_id=?", msg.id, guild.id, member.id)
        try:
            await msg.pin()
        except discord.HTTPException:
            pass


async def setup(bot):
    await bot.add_cog(Cabinets(bot))
