import asyncio
import os
from typing import Union

import discord
from discord.ext import commands

import blueprint
import config
import ui

PANEL_HELP = {
    "apply": "ch_apply", "support": "ch_support", "afk": "ch_afk", "shifts": "ch_shifts",
    "shop": "ch_shop", "cabinet": "ch_cabinet", "rules": "ch_rules",
}


def _env_id(names) -> int:
    for n in names or []:
        v = (os.getenv(n) or "").strip()
        if v.isdigit() and int(v):
            return int(v)
    return 0


class Setup(commands.Cog):
    """Команда !setup: создаёт роли, категории, каналы, права и панели, и привязывает их к командам бота."""

    def __init__(self, bot):
        self.bot = bot
        self._running: set[int] = set()

    # ---------------------------------------------------------- роли
    async def _ensure_role(self, guild: discord.Guild, spec: dict):
        db = self.bot.db
        rid = await db.get_setting(guild.id, spec["key"])
        role = guild.get_role(rid) if rid else None
        how = "привязана"
        if not role:
            eid = _env_id(spec.get("env"))
            role = guild.get_role(eid) if eid else None
            how = "найдена по ID из .env"
        if not role:
            role = discord.utils.get(guild.roles, name=spec["name"])
            how = "найдена по названию"
        if not role and spec.get("create", True):
            role = await guild.create_role(
                name=spec["name"], colour=discord.Colour(spec["color"]), hoist=spec.get("hoist", False),
                mentionable=spec.get("mentionable", False), permissions=discord.Permissions(**spec["perms"]),
                reason="!setup")
            how = "создана"
        if role:
            await db.set_setting(guild.id, spec["key"], role.id)
            return role, how
        return None, "пропущена (не найдена)"

    async def _arrange_roles(self, guild: discord.Guild, roles: dict):
        """Расставляет созданные роли по иерархии под ролью бота."""
        top = guild.me.top_role.position - 1
        positions, pos = {}, top
        for spec in blueprint.ROLES:
            role = roles.get(spec["key"])
            if not role or role.managed or role.position >= guild.me.top_role.position:
                continue
            if pos < 1:
                break
            positions[role] = pos
            pos -= 1
        if positions:
            try:
                await guild.edit_role_positions(positions=positions, reason="!setup")
            except discord.HTTPException:
                pass

    # ---------------------------------------------------------- каналы
    async def _ensure_category(self, guild, spec, roles, force):
        db = self.bot.db
        cat = None
        if spec.get("key"):
            cid = await db.get_setting(guild.id, spec["key"])
            cat = guild.get_channel(cid) if cid else None
            if cat is not None and not isinstance(cat, discord.CategoryChannel):
                cat = None
        if not cat:
            cat = discord.utils.get(guild.categories, name=spec["name"])
        ow = blueprint.build_overwrites(guild, spec["access"], "text", roles)
        how = "найдена"
        if not cat:
            cat = await guild.create_category(spec["name"], overwrites=ow, reason="!setup")
            how = "создана"
        elif force:
            await cat.edit(overwrites=ow, reason="!setup force")
        if spec.get("key"):
            await db.set_setting(guild.id, spec["key"], cat.id)
        return cat, how

    async def _ensure_channel(self, guild, cat, cat_access, spec, roles, force):
        db = self.bot.db
        kind = spec.get("kind", "text")
        chan = None
        key = spec.get("key")
        if key:
            cid = await db.get_setting(guild.id, key)
            chan = guild.get_channel(cid) if cid else None
            if not chan:
                eid = _env_id(spec.get("env"))
                chan = guild.get_channel(eid) if eid else None
        if not chan:
            wanted = blueprint.norm_name(spec["name"], kind)
            chan = discord.utils.get(cat.channels, name=wanted)
        ow = blueprint.build_overwrites(guild, spec.get("access", cat_access), kind, roles)
        how = "найден"
        if not chan:
            if kind == "voice":
                chan = await guild.create_voice_channel(spec["name"], category=cat, overwrites=ow, reason="!setup")
            else:
                chan = await guild.create_text_channel(spec["name"], category=cat, overwrites=ow,
                                                       topic=spec.get("topic"), reason="!setup")
            how = "создан"
        elif force:
            await chan.edit(overwrites=ow, reason="!setup force")
        if key:
            await db.set_setting(guild.id, key, chan.id)
        return chan, how

    # ---------------------------------------------------------- панели
    async def post_panel_for(self, guild: discord.Guild, channel_key: str):
        spec = next((c for cat in blueprint.categories() for c in cat["channels"] if c.get("key") == channel_key), None)
        if not spec or not spec.get("panel"):
            return False
        channel = guild.get_channel(await self.bot.db.get_setting(guild.id, channel_key) or 0)
        cog = self.bot.get_cog(spec["panel"])
        if not channel or not cog:
            return False
        try:
            await channel.purge(limit=30, check=lambda m: m.author.id == self.bot.user.id)
        except discord.HTTPException:
            pass
        await cog.post_panel(channel, channel_key)
        return True

    async def run_setup(self, guild: discord.Guild, force: bool = False):
        report = {"roles": [], "cats": [], "chans": []}
        roles = {}
        for spec in blueprint.ROLES:
            role, how = await self._ensure_role(guild, spec)
            roles[spec["key"]] = role
            report["roles"].append((spec["name"], how))
        await self._arrange_roles(guild, roles)

        for cspec in blueprint.categories():
            cat, how = await self._ensure_category(guild, cspec, roles, force)
            report["cats"].append((cspec["name"], how))
            for chspec in cspec["channels"]:
                chan, how = await self._ensure_channel(guild, cat, cspec["access"], chspec, roles, force)
                report["chans"].append((chspec["name"], how))
                await asyncio.sleep(0.3)

        panels = 0
        for cspec in blueprint.categories():
            for chspec in cspec["channels"]:
                if chspec.get("panel") and await self.post_panel_for(guild, chspec["key"]):
                    panels += 1
        return report, panels

    @staticmethod
    def _summary(report, panels) -> discord.Embed:
        def count(items, word):
            return sum(1 for _, h in items if h == word)

        e = ui.make("⚙️ Сервер настроен", f"Роли, каналы и панели связаны с командами бота.\n{ui.DIV}", banner=True)
        e.add_field(name="🎭 Роли", value=f"создано **{count(report['roles'], 'создана')}** • "
                                          f"найдено **{sum(1 for _, h in report['roles'] if h.startswith(('найд', 'прив')))}**",
                    inline=False)
        e.add_field(name="📂 Категории", value=f"создано **{count(report['cats'], 'создана')}** • "
                                                f"найдено **{count(report['cats'], 'найдена')}**", inline=False)
        e.add_field(name="💬 Каналы", value=f"создано **{count(report['chans'], 'создан')}** • "
                                             f"найдено **{count(report['chans'], 'найден')}**", inline=False)
        e.add_field(name="🧩 Панели", value=f"отправлено **{panels}**", inline=False)
        skipped = [n for n, h in report["roles"] if h.startswith("пропущ")]
        if skipped:
            e.add_field(name="⚠️ Не найдены", value="\n".join(skipped) +
                        "\nПривяжите вручную: `!setup bind role_booster @Роль`", inline=False)
        e.add_field(name="Дальше", value="Выдайте себе/штабу роли **Owner/High/Recruiter**, затем проверьте "
                                         "`!setup status`. Роль бота должна быть выше выдаваемых ролей.",
                    inline=False)
        return e

    # ---------------------------------------------------------- команды
    @commands.group(name="setup", invoke_without_command=True)
    @commands.guild_only()
    @commands.has_guild_permissions(administrator=True)
    async def setup_cmd(self, ctx: commands.Context):
        """!setup — создать всё. !setup force — ещё и пересобрать права. !setup status|panels|bind"""
        await self._start(ctx, force=False)

    async def _start(self, ctx, force: bool):
        if ctx.guild.id in self._running:
            return await ctx.send(embed=ui.err("Настройка уже выполняется."))
        self._running.add(ctx.guild.id)
        msg = await ctx.send(embed=ui.make("⚙️ Настройка сервера", "Создаю роли, каналы и панели… "
                                           "это займёт около минуты."))
        try:
            report, panels = await self.run_setup(ctx.guild, force)
            await msg.edit(embed=self._summary(report, panels))
        except discord.Forbidden:
            await msg.edit(embed=ui.err("Не хватает прав. Выдайте боту **Administrator** "
                                        "(или Manage Roles/Channels) и повторите `!setup`."))
        finally:
            self._running.discard(ctx.guild.id)

    @setup_cmd.command(name="force")
    @commands.has_guild_permissions(administrator=True)
    async def setup_force(self, ctx):
        """Пересобрать права у всех каналов и категорий по схеме."""
        await self._start(ctx, force=True)

    @setup_cmd.command(name="panels")
    @commands.has_guild_permissions(administrator=True)
    async def setup_panels(self, ctx):
        """Отправить панели заново (старые сообщения бота в этих каналах удаляются)."""
        n = 0
        for cspec in blueprint.categories():
            for chspec in cspec["channels"]:
                if chspec.get("panel") and await self.post_panel_for(ctx.guild, chspec["key"]):
                    n += 1
        await ctx.send(embed=ui.ok(f"Панелей отправлено: **{n}**"))

    @setup_cmd.command(name="status")
    @commands.has_guild_permissions(administrator=True)
    async def setup_status(self, ctx):
        """Показать, что к чему привязано."""
        settings = await self.bot.db.settings_like(ctx.guild.id, "")
        role_lines, chan_lines = [], []
        for spec in blueprint.ROLES:
            rid = settings.get(spec["key"])
            role_lines.append(f"`{spec['key']}` → " + (f"<@&{rid}>" if rid else "❌"))
        for cspec in blueprint.categories():
            keys = ([cspec["key"]] if cspec.get("key") else []) + [c["key"] for c in cspec["channels"] if c.get("key")]
            for k in keys:
                cid = settings.get(k)
                chan_lines.append(f"`{k}` → " + (f"<#{cid}>" if cid else "❌"))
        e1 = ui.make("🎭 Привязка ролей", "\n".join(role_lines))
        e2 = ui.make("💬 Привязка каналов", "\n".join(chan_lines)[:4000])
        await ctx.send(embeds=[e1, e2])

    @setup_cmd.command(name="bind")
    @commands.has_guild_permissions(administrator=True)
    async def setup_bind(self, ctx, key: str, target: Union[discord.Role, discord.abc.GuildChannel]):
        """!setup bind <ключ> <@роль или #канал> — привязать вручную."""
        valid = {s["key"] for s in blueprint.ROLES}
        for c in blueprint.categories():
            if c.get("key"):
                valid.add(c["key"])
            valid |= {x["key"] for x in c["channels"] if x.get("key")}
        if key not in valid:
            return await ctx.send(embed=ui.err("Неизвестный ключ. Список — в `!setup status`."))
        await self.bot.db.set_setting(ctx.guild.id, key, target.id)
        await ctx.send(embed=ui.ok(f"`{key}` → {target.mention}"))

    @commands.command(name="panel")
    @commands.guild_only()
    @commands.has_guild_permissions(administrator=True)
    async def panel_cmd(self, ctx, name: str = ""):
        """!panel apply|support|afk|shifts|shop|cabinet|rules — отправить панель в ТЕКУЩИЙ канал."""
        key = PANEL_HELP.get(name.lower())
        if not key:
            return await ctx.send(embed=ui.err("Доступно: " + ", ".join(f"`{k}`" for k in PANEL_HELP)))
        spec = next(c for cat in blueprint.categories() for c in cat["channels"] if c.get("key") == key)
        await self.bot.get_cog(spec["panel"]).post_panel(ctx.channel, key)
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass


async def setup(bot):
    await bot.add_cog(Setup(bot))
