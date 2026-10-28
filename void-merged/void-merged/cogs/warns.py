import time

import discord
from discord import app_commands
from discord.ext import commands

from config import cfg
from utils import FieldsModal, admin_only, clip, deny, embed, is_staff, send_to, set_role

STAGES = "`1/3` — первый выговор\n`2/3` — второй выговор\n`3/3` — отстранение от каптов"


async def give_warn(bot, guild, uid, reason, issuer):
    db = bot.db
    r = await db.one("SELECT level FROM warns WHERE user_id=?", uid)
    lvl = min(3, (r["level"] if r else 0) + 1)
    now = time.time()
    await db.run(
        "INSERT INTO warns VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET level=?, reason=?, issued_by=?, ts=?",
        uid, lvl, reason, issuer, now, lvl, reason, issuer, now)
    member = guild.get_member(uid)
    if lvl == 3 and member:
        await set_role(member, cfg.capt_ban_role_id, True)
    note = "Вы отстранены от каптов." if lvl == 3 else ""
    await send_to(bot, cfg.notify_channel_id, content=f"<@{uid}>", embed=embed(
        f"Выговор {lvl}/3", f"Причина: {reason}\nВыдал: <@{issuer}>\n{note}", color=0xE74C3C))
    return lvl


async def take_warn(bot, guild, uid):
    db = bot.db
    r = await db.one("SELECT level FROM warns WHERE user_id=?", uid)
    if not r:
        return None
    lvl = r["level"] - 1
    if lvl <= 0:
        await db.run("DELETE FROM warns WHERE user_id=?", uid)
        lvl = 0
    else:
        await db.run("UPDATE warns SET level=? WHERE user_id=?", lvl, uid)
    member = guild.get_member(uid)
    if r["level"] == 3 and member:
        await set_role(member, cfg.capt_ban_role_id, False)
    return lvl


async def warns_embed(db):
    rows = await db.all("SELECT * FROM warns ORDER BY level DESC")
    e = embed("Панель выговоров", "Показывает участников с активными выговорами.\n\n**Стадии:**\n" + STAGES)
    e.add_field(
        name="Текущие выговоры",
        value=clip("\n".join(f"`{r['level']}/3` <@{r['user_id']}> — {(r['reason'] or '')[:60]}" for r in rows), 1000)
        or "Ни у кого нет выговоров.",
        inline=False)
    return e


class WarnsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _pick_user(self, i, on_user):
        v = discord.ui.View(timeout=120)
        sel = discord.ui.UserSelect(placeholder="Выберите участника")

        async def cb(inter):
            await on_user(inter, sel.values[0])

        sel.callback = cb
        v.add_item(sel)
        await i.response.send_message("Кому?", view=v, ephemeral=True)

    @discord.ui.button(label="Выдать выговор", custom_id="warn:give", style=discord.ButtonStyle.danger)
    async def give(self, i: discord.Interaction, _):
        if not is_staff(i.user):
            return await deny(i)
        panel = i.message

        async def on_user(inter, user):
            async def done(m_inter, f):
                lvl = await give_warn(m_inter.client, m_inter.guild, user.id, f["reason"], m_inter.user.id)
                await m_inter.response.send_message(f"{user.mention}: выговор {lvl}/3.", ephemeral=True)
                try:
                    await panel.edit(embed=await warns_embed(m_inter.client.db))
                except discord.HTTPException:
                    pass

            await inter.response.send_modal(FieldsModal("Причина выговора", [("reason", "Причина")], done))

        await self._pick_user(i, on_user)

    @discord.ui.button(label="Снять выговор", custom_id="warn:take", style=discord.ButtonStyle.success)
    async def take(self, i: discord.Interaction, _):
        if not is_staff(i.user):
            return await deny(i)
        panel = i.message

        async def on_user(inter, user):
            lvl = await take_warn(inter.client, inter.guild, user.id)
            if lvl is None:
                return await inter.response.send_message("У участника нет выговоров.", ephemeral=True)
            await inter.response.send_message(f"{user.mention}: теперь {lvl}/3.", ephemeral=True)
            try:
                await panel.edit(embed=await warns_embed(inter.client.db))
            except discord.HTTPException:
                pass

        await self._pick_user(i, on_user)


class Warns(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(WarnsView())

    @app_commands.command(name="panel_warns", description="Панель выговоров")
    @admin_only()
    async def panel(self, i: discord.Interaction):
        await i.response.send_message(embed=await warns_embed(self.bot.db), view=WarnsView())


async def setup(bot):
    await bot.add_cog(Warns(bot))
