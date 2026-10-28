import time

import discord
from discord import app_commands
from discord.ext import commands

from config import cfg
from utils import admin_only, clip, deny, embed, fmt_dur, is_staff

INACTIVE_HOURS = 5  # меньше этого за 30 дней в войсе = инактив

BUTTONS = [
    ("Рекрутёр", "st:rec"), ("Тир-чекеры", "st:tch"), ("Портфели", "st:port"),
    ("Голосовая активность", "st:voice"), ("Участники", "st:members"), ("Инактив", "st:inactive"),
    ("Снимок войса", "st:snap"), ("Нет в войсе", "st:novoice"), ("Обновить", "st:refresh"),
    ("Проверка игрока", "st:check"),
]


def family(guild):
    if cfg.member_role_id:
        r = guild.get_role(cfg.member_role_id)
        return [m for m in (r.members if r else []) if not m.bot]
    return [m for m in guild.members if not m.bot]


async def voice_totals(db, days=30):
    since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - days * 86400))
    rows = await db.all("SELECT user_id, SUM(seconds) AS s FROM voice_days WHERE day>=? GROUP BY user_id", since)
    tot = {r["user_id"]: r["s"] for r in rows}
    now = time.time()
    for r in await db.all("SELECT * FROM voice_sessions"):
        tot[r["user_id"]] = tot.get(r["user_id"], 0) + int(now - r["joined"])
    return tot


async def staff_rows(db, kind, days=30):
    return await db.all(
        "SELECT user_id, COUNT(*) AS n FROM staff_actions WHERE role_kind=? AND ts>? "
        "GROUP BY user_id ORDER BY n DESC", kind, time.time() - days * 86400)


async def stats_embed(bot, guild):
    e = embed("Центр мониторинга персонала", "Сводная статистика активности за **30 дней**.")
    for title, kind, rid in (("Рекрутёр", "recruiter", cfg.recruiter_role_id),
                             ("Тир-чекеры", "tierchecker", cfg.tierchecker_role_id)):
        rows = await staff_rows(bot.db, kind)
        role = guild.get_role(rid) if rid else None
        top = f"<@{rows[0]['user_id']}>" if rows else "—"
        e.add_field(
            name=title,
            value=f"Сотрудников: `{len(role.members) if role else 0}`\n"
                  f"Действий: `{sum(r['n'] for r in rows)}`\nТоп: {top}")
    return e


async def reply(i, title, text):
    await i.response.send_message(embed=embed(title, clip(text) or "Нет данных."), ephemeral=True)


async def player_profile(db, guild, member):
    tot = await voice_totals(db)
    warn = await db.one("SELECT level FROM warns WHERE user_id=?", member.id)
    port = await db.one("SELECT url FROM portfolios WHERE user_id=?", member.id)
    rb = await db.one("SELECT COUNT(*) AS c FROM rollbacks WHERE user_id=?", member.id)
    pts = await db.one("SELECT balance FROM points WHERE user_id=?", member.id)
    vac = await db.one("SELECT until FROM vacations WHERE user_id=?", member.id)
    e = embed(f"Проверка игрока: {member.display_name}")
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="Войс за 30 дней", value=fmt_dur(tot.get(member.id, 0)))
    e.add_field(name="Выговор", value=f"{warn['level']}/3" if warn else "нет")
    e.add_field(name="Откатов", value=str(rb["c"]))
    e.add_field(name="Баллы", value=str(pts["balance"] if pts else 0))
    e.add_field(name="Отпуск", value=f"до <t:{int(vac['until'])}:d>" if vac else "нет")
    e.add_field(name="Портфель", value=port["url"] if port else "нет", inline=False)
    return e


class StatsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for label, cid in BUTTONS:
            b = discord.ui.Button(label=label, custom_id=cid, style=discord.ButtonStyle.secondary)
            b.callback = self.click
            self.add_item(b)

    async def click(self, i: discord.Interaction):
        if not is_staff(i.user):
            return await deny(i)
        cid, bot, g = i.data["custom_id"], i.client, i.guild
        db = bot.db

        if cid == "st:refresh":
            return await i.response.edit_message(embed=await stats_embed(bot, g))
        if cid in ("st:rec", "st:tch"):
            rows = await staff_rows(db, "recruiter" if cid == "st:rec" else "tierchecker")
            return await reply(i, "Действия за 30 дней", "\n".join(
                f"{n}. <@{r['user_id']}> — `{r['n']}`" for n, r in enumerate(rows[:15], 1)))
        if cid == "st:port":
            rows = await db.all("SELECT * FROM portfolios ORDER BY created DESC LIMIT 15")
            return await reply(i, "Портфели", "\n".join(f"<@{r['user_id']}> — {r['url']}" for r in rows))
        if cid == "st:voice":
            tot = sorted((await voice_totals(db)).items(), key=lambda kv: -kv[1])[:15]
            return await reply(i, "Голосовая активность (30 дней)", "\n".join(
                f"{n}. <@{u}> — {fmt_dur(s)}" for n, (u, s) in enumerate(tot, 1)))
        if cid == "st:members":
            ms = family(g)
            return await reply(i, f"Участники ({len(ms)})", ", ".join(m.mention for m in ms[:80]))
        if cid == "st:inactive":
            tot = await voice_totals(db)
            ms = [m for m in family(g) if tot.get(m.id, 0) < INACTIVE_HOURS * 3600]
            return await reply(i, f"Инактив: < {INACTIVE_HOURS}ч за 30 дней ({len(ms)})",
                               ", ".join(m.mention for m in ms[:80]))
        if cid == "st:snap":
            lines = []
            for vc in g.voice_channels:
                mem = [m.mention for m in vc.members if not m.bot]
                if mem:
                    lines.append(f"**{vc.name}** ({len(mem)})\n" + ", ".join(mem))
            return await reply(i, "Снимок войса", "\n\n".join(lines))
        if cid == "st:novoice":
            ms = [m for m in family(g) if not m.voice]
            return await reply(i, f"Нет в войсе ({len(ms)})", ", ".join(m.mention for m in ms[:80]))
        if cid == "st:check":
            v = discord.ui.View(timeout=120)
            sel = discord.ui.UserSelect(placeholder="Выберите игрока")

            async def cb(inter):
                m = sel.values[0]
                m = g.get_member(m.id) or m
                if not isinstance(m, discord.Member):
                    return await deny(inter, "Игрок не на сервере.")
                await inter.response.send_message(embed=await player_profile(db, g, m), ephemeral=True)

            sel.callback = cb
            v.add_item(sel)
            await i.response.send_message("Кого проверяем?", view=v, ephemeral=True)


class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(StatsView())

    @app_commands.command(name="panel_stats", description="Центр мониторинга персонала")
    @admin_only()
    async def panel(self, i: discord.Interaction):
        await i.response.send_message(embed=await stats_embed(self.bot, i.guild), view=StatsView())

    @commands.Cog.listener()
    async def on_ready(self):
        guild = self.bot.get_guild(cfg.guild_id)
        if not guild:
            return
        now = time.time()
        for vc in guild.voice_channels:
            for m in vc.members:
                if not m.bot and vc != guild.afk_channel:
                    await self.bot.db.run("INSERT OR IGNORE INTO voice_sessions VALUES(?,?)", m.id, now)

    @commands.Cog.listener()
    async def on_voice_state_update(self, m, before, after):
        if m.bot or m.guild.id != cfg.guild_id:
            return
        afk = m.guild.afk_channel
        was = before.channel is not None and before.channel != afk
        now_in = after.channel is not None and after.channel != afk
        if not was and now_in:
            await self.bot.db.run("INSERT OR REPLACE INTO voice_sessions VALUES(?,?)", m.id, time.time())
        elif was and not now_in:
            await self.close_session(m.id)

    async def close_session(self, uid):
        db = self.bot.db
        r = await db.one("SELECT joined FROM voice_sessions WHERE user_id=?", uid)
        if not r:
            return
        secs = max(0, int(time.time() - r["joined"]))
        day = time.strftime("%Y-%m-%d", time.gmtime())
        await db.run(
            "INSERT INTO voice_days VALUES(?,?,?) ON CONFLICT(user_id,day) DO UPDATE SET seconds=seconds+?",
            uid, day, secs, secs)
        rate = int(await db.get("farm_rate", "1"))
        if secs // 60 * rate:
            await db.add_points(uid, secs // 60 * rate)
        await db.run("DELETE FROM voice_sessions WHERE user_id=?", uid)


async def setup(bot):
    await bot.add_cog(Stats(bot))
