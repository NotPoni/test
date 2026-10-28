import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import cfg
from utils import FieldsModal, admin_only, deny, embed, send_to, set_role, to_int

DEFAULT_GUIDES = "Ссылки на гайды по каптам и MCL добавляются командой /set_guides."


async def pick_rollback(i):
    v = discord.ui.View(timeout=120)
    sel = discord.ui.Select(placeholder="Тип отката", options=[
        discord.SelectOption(label="MCL", value="MCL"), discord.SelectOption(label="Капт", value="Капт")])

    async def cb(inter):
        kind = sel.values[0]

        async def done(m_inter, f):
            if not f["url"].startswith("http"):
                return await m_inter.response.send_message("Нужна ссылка (http...).", ephemeral=True)
            await m_inter.client.db.run(
                "INSERT INTO rollbacks(user_id,kind,url,ts) VALUES(?,?,?,?)",
                m_inter.user.id, kind, f["url"], time.time())
            await send_to(m_inter.client, cfg.rollback_channel_id, embed=embed(
                f"Откат • {kind}", f"{m_inter.user.mention}\n{f['url']}"))
            await m_inter.response.send_message("Откат отправлен.", ephemeral=True)

        await inter.response.send_modal(FieldsModal(f"Откат: {kind}", [("url", "Ссылка на запись")], done))

    sel.callback = cb
    v.add_item(sel)
    await i.response.send_message("Выберите тип:", view=v, ephemeral=True)


class InteractionsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Отпуск", custom_id="ia:vac", style=discord.ButtonStyle.secondary)
    async def vac(self, i: discord.Interaction, _):
        db = i.client.db
        if await db.one("SELECT 1 FROM vacations WHERE user_id=?", i.user.id):
            await db.run("DELETE FROM vacations WHERE user_id=?", i.user.id)
            await set_role(i.user, cfg.vacation_role_id, False)
            return await i.response.send_message("С возвращением! Отпуск завершён.", ephemeral=True)

        async def done(inter, f):
            days = to_int(f["days"])
            if not days or not 1 <= days <= 30:
                return await inter.response.send_message("Срок: от 1 до 30 дней.", ephemeral=True)
            until = time.time() + days * 86400
            await db.run("INSERT OR REPLACE INTO vacations VALUES(?,?,?)", inter.user.id, until, f["reason"])
            await set_role(inter.user, cfg.vacation_role_id, True)
            await inter.response.send_message(
                f"Отпуск до <t:{int(until)}:d>. Нажмите «Отпуск» ещё раз, чтобы вернуться раньше.", ephemeral=True)

        await i.response.send_modal(FieldsModal("Отпуск", [("days", "Дней (1-30)"), ("reason", "Причина")], done))

    @discord.ui.button(label="Портфель", custom_id="ia:port", style=discord.ButtonStyle.secondary)
    async def port(self, i: discord.Interaction, _):
        async def done(inter, f):
            if not f["url"].startswith("http"):
                return await inter.response.send_message("Нужна ссылка (http...).", ephemeral=True)
            await inter.client.db.run("INSERT OR REPLACE INTO portfolios VALUES(?,?,?)", inter.user.id, f["url"], time.time())
            await inter.response.send_message("Портфель сохранён.", ephemeral=True)

        await i.response.send_modal(FieldsModal("Портфель", [("url", "Ссылка на портфель")], done))

    @discord.ui.button(label="Откат", custom_id="ia:roll", style=discord.ButtonStyle.primary)
    async def roll(self, i, _):
        await pick_rollback(i)

    @discord.ui.button(label="AFK", custom_id="ia:afk", style=discord.ButtonStyle.secondary)
    async def afk(self, i: discord.Interaction, _):
        db = i.client.db
        r = await db.one("SELECT since FROM afk WHERE user_id=?", i.user.id)
        if r:
            await db.run("DELETE FROM afk WHERE user_id=?", i.user.id)
            await set_role(i.user, cfg.afk_role_id, False)
            mins = int((time.time() - r["since"]) // 60)
            return await i.response.send_message(f"Вы вернулись из AFK (отсутствовали {mins} мин).", ephemeral=True)
        await db.run("INSERT OR REPLACE INTO afk VALUES(?,?)", i.user.id, time.time())
        await set_role(i.user, cfg.afk_role_id, True)
        await i.response.send_message("Вы в AFK. Нажмите ещё раз, чтобы вернуться.", ephemeral=True)

    @discord.ui.button(label="Гайды", custom_id="ia:guides", style=discord.ButtonStyle.secondary)
    async def guides(self, i, _):
        text = await i.client.db.get("guides", DEFAULT_GUIDES)
        await i.response.send_message(embed=embed("Гайды по каптам и MCL", text), ephemeral=True)


class Interactions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(InteractionsView())
        self.vac_loop.start()

    async def cog_unload(self):
        self.vac_loop.cancel()

    @app_commands.command(name="panel_interactions", description="Центр личных взаимодействий с ботом")
    @admin_only()
    async def panel(self, i: discord.Interaction):
        e = embed("Центр личных взаимодействий с ботом",
                  "Отпуск · Портфель · Откат (MCL/Капт) · AFK · Гайды")
        await i.response.send_message(embed=e, view=InteractionsView())

    @app_commands.command(name="set_guides", description="Задать текст раздела «Гайды»")
    @app_commands.describe(text="Текст/ссылки на гайды")
    @admin_only()
    async def set_guides(self, i: discord.Interaction, text: str):
        await self.bot.db.put("guides", text[:3900])
        await i.response.send_message("Сохранено.", ephemeral=True)

    @tasks.loop(minutes=10)
    async def vac_loop(self):
        db = self.bot.db
        guild = self.bot.get_guild(cfg.guild_id)
        for r in await db.all("SELECT user_id FROM vacations WHERE until<?", time.time()):
            m = guild.get_member(r["user_id"]) if guild else None
            if m:
                await set_role(m, cfg.vacation_role_id, False)
            await db.run("DELETE FROM vacations WHERE user_id=?", r["user_id"])

    @vac_loop.before_loop
    async def _wait(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Interactions(bot))
