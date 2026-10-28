import time

import discord
from discord import app_commands
from discord.ext import commands

import config
import ui
from checks import send_log


class ShiftView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Начать смену", emoji="🟢", style=discord.ButtonStyle.success, custom_id="shift:start")
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = interaction.client.db
        g, u = interaction.guild_id, interaction.user.id
        if await db.fetchone("SELECT 1 FROM shifts WHERE guild_id=? AND user_id=?", g, u):
            return await interaction.response.send_message(embed=ui.err("Вы уже на смене."), ephemeral=True)
        await db.execute("INSERT INTO shifts(guild_id,user_id,start) VALUES(?,?,?)", g, u, int(time.time()))
        await interaction.response.send_message(embed=ui.ok("Смена начата. Удачной работы!"), ephemeral=True)
        e = ui.make("🟢 Начало смены", f"{interaction.user.mention} заступил на смену.", color=config.COLOR_OK)
        await send_log(interaction.client, interaction.guild, e)

    @discord.ui.button(label="Закончить смену", emoji="🔴", style=discord.ButtonStyle.danger, custom_id="shift:end")
    async def end(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = interaction.client.db
        g, u = interaction.guild_id, interaction.user.id
        row = await db.fetchone("SELECT start FROM shifts WHERE guild_id=? AND user_id=?", g, u)
        if not row:
            return await interaction.response.send_message(embed=ui.err("Вы не на смене."), ephemeral=True)
        dur = int(time.time()) - row["start"]
        await db.execute("DELETE FROM shifts WHERE guild_id=? AND user_id=?", g, u)
        await db.execute(
            "INSERT INTO shift_totals(guild_id,user_id,seconds,count) VALUES(?,?,?,1) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET seconds=seconds+excluded.seconds, count=count+1",
            g, u, dur)
        await interaction.response.send_message(
            embed=ui.ok(f"Смена завершена. Длительность: **{ui.fmt_time(dur)}**"), ephemeral=True)
        e = ui.make("🔴 Конец смены", f"{interaction.user.mention} закончил смену — **{ui.fmt_time(dur)}**.",
                    color=config.COLOR_ERR)
        await send_log(interaction.client, interaction.guild, e)

    @discord.ui.button(label="Кто на смене", emoji="👥", style=discord.ButtonStyle.secondary, custom_id="shift:online")
    async def online(self, interaction: discord.Interaction, button: discord.ui.Button):
        rows = await interaction.client.db.fetchall(
            "SELECT user_id,start FROM shifts WHERE guild_id=? ORDER BY start", interaction.guild_id)
        text = "\n".join(
            f"• <@{r['user_id']}> — <t:{r['start']}:R>" for r in rows) or "Сейчас никто не на смене."
        await interaction.response.send_message(
            embed=ui.make(f"👥 На смене: {len(rows)}", text), ephemeral=True)

    @discord.ui.button(label="Моя статистика", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="shift:stats")
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await interaction.client.db.fetchone(
            "SELECT seconds,count FROM shift_totals WHERE guild_id=? AND user_id=?",
            interaction.guild_id, interaction.user.id)
        sec, cnt = (row["seconds"], row["count"]) if row else (0, 0)
        e = ui.make("📊 Ваша статистика", thumbnail=interaction.user.display_avatar.url)
        e.add_field(name="Всего времени", value=ui.fmt_time(sec))
        e.add_field(name="Смен", value=str(cnt))
        await interaction.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="Топ", emoji="🏆", style=discord.ButtonStyle.secondary, custom_id="shift:top")
    async def top(self, interaction: discord.Interaction, button: discord.ui.Button):
        rows = await interaction.client.db.fetchall(
            "SELECT user_id,seconds FROM shift_totals WHERE guild_id=? ORDER BY seconds DESC LIMIT 10",
            interaction.guild_id)
        medals = ["🥇", "🥈", "🥉"]
        text = "\n".join(
            f"{medals[i] if i < 3 else f'`{i + 1}.`'} <@{r['user_id']}> — **{ui.fmt_time(r['seconds'])}**"
            for i, r in enumerate(rows)) or "Пока пусто."
        await interaction.response.send_message(embed=ui.make("🏆 Топ по времени на смене", text), ephemeral=True)


class Shifts(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(ShiftView())

    @app_commands.command(name="панель_смен", description="Отправить панель учёта смен в этот канал")
    @app_commands.default_permissions(administrator=True)
    async def panel(self, interaction: discord.Interaction):
        e = ui.make(
            "⏱️ Учёт рабочих смен",
            f"Заступай на смену и закрывай её кнопками ниже.\n{ui.DIV}\n"
            "🟢 начать • 🔴 закончить • 👥 кто на смене • 📊 статистика • 🏆 топ",
            banner=True,
        )
        await interaction.channel.send(embed=e, view=ShiftView())
        await interaction.response.send_message(embed=ui.ok("Панель отправлена."), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Shifts(bot))
