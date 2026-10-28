import json

import discord
from discord import app_commands
from discord.ext import commands

import ui
from checks import staff_only


def build_embed(d: dict) -> discord.Embed:
    members = json.loads(d["members"])
    e = ui.make(f"📅 {d['title']}", d["description"] or None)
    e.add_field(name="🕒 Время", value=d["starts"])
    e.add_field(name="🎙️ Организатор", value=f"<@{d['author_id']}>")
    listing = "\n".join(f"`{i + 1}.` <@{u}>" for i, u in enumerate(members)) or "—"
    e.add_field(name=f"👥 Участники ({len(members)}/{d['slots']})", value=listing, inline=False)
    return e


class EventView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _load(self, interaction):
        row = await interaction.client.db.fetchone(
            "SELECT * FROM events WHERE message_id=?", interaction.message.id)
        if not row:
            await interaction.response.send_message(embed=ui.err("Сбор не найден."), ephemeral=True)
            return None
        return dict(row)

    async def _save(self, interaction, d, members):
        d["members"] = json.dumps(members)
        await interaction.client.db.execute(
            "UPDATE events SET members=? WHERE message_id=?", d["members"], d["message_id"])
        await interaction.response.edit_message(embed=build_embed(d))

    @discord.ui.button(label="Иду", emoji="✅", style=discord.ButtonStyle.success, custom_id="event:join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        d = await self._load(interaction)
        if not d:
            return
        members = json.loads(d["members"])
        if interaction.user.id in members:
            return await interaction.response.send_message(embed=ui.err("Вы уже записаны."), ephemeral=True)
        if len(members) >= d["slots"]:
            return await interaction.response.send_message(embed=ui.err("Мест больше нет."), ephemeral=True)
        members.append(interaction.user.id)
        await self._save(interaction, d, members)

    @discord.ui.button(label="Отказаться", emoji="❌", style=discord.ButtonStyle.danger, custom_id="event:leave")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        d = await self._load(interaction)
        if not d:
            return
        members = json.loads(d["members"])
        if interaction.user.id not in members:
            return await interaction.response.send_message(embed=ui.err("Вы не записаны."), ephemeral=True)
        members.remove(interaction.user.id)
        await self._save(interaction, d, members)


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(EventView())

    @app_commands.command(name="сбор", description="Создать сбор на мероприятие")
    @app_commands.describe(title="Название", time="Когда (например: сегодня 20:00)", slots="Количество мест",
                           description="Описание/условия", ping="Кого упомянуть")
    @staff_only()
    async def gather(self, interaction: discord.Interaction, title: str, time: str, slots: int = 20,
                     description: str | None = None, ping: discord.Role | None = None):
        d = {"title": title, "description": description, "starts": time, "slots": slots,
             "author_id": interaction.user.id, "members": "[]"}
        await interaction.response.send_message(
            content=ping.mention if ping else None, embed=build_embed(d), view=EventView(),
            allowed_mentions=discord.AllowedMentions(roles=True))
        msg = await interaction.original_response()
        await self.bot.db.execute(
            "INSERT INTO events(message_id,guild_id,author_id,title,description,starts,slots) VALUES(?,?,?,?,?,?,?)",
            msg.id, interaction.guild_id, interaction.user.id, title, description, time, slots)


async def setup(bot):
    await bot.add_cog(Events(bot))
