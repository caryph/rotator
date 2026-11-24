"""Minimal Discord leveling bot. discord.py v2, hybrid commands, per-guild XP."""

import math
import os
import random
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

import db

load_dotenv()

XP_MIN, XP_MAX = 15, 20
COOLDOWN_MIN_SECS, COOLDOWN_MAX_SECS = 25, 35
OWNER_ID = 520293520418930690


def xp_for_level(level: int) -> int:
    """XP needed to reach a level: 1@0, 2@50, 3@200, 4@450, 10@4050."""
    return (level - 1) ** 2 * 50


def level_for(xp: int) -> int:
    """Inverse of xp_for_level."""
    return math.isqrt(xp // 50) + 1


intents = discord.Intents.default()
# also requires the Message Content Intent toggle in the Discord dev portal,
# otherwise on_message never fires in servers and no XP is ever awarded.
intents.message_content = True

bot = commands.Bot(command_prefix="r!", intents=intents)
bot.remove_command("help")


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")


# bot.listen instead of @bot.event: a plain on_message here would replace
# Bot.on_message and silently kill every prefix/hybrid command.
@bot.listen()
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    now = time.time()
    member = db.get_member(message.guild.id, message.author.id)

    if member and now < member.xp_cooldown:
        return

    gained = random.randint(XP_MIN, XP_MAX)
    cooldown_until = now + random.randint(COOLDOWN_MIN_SECS, COOLDOWN_MAX_SECS)
    db.add_xp(message.guild.id, message.author.id, gained, cooldown_until)

    print(
        f"+{gained} xp -> {message.author} in {message.guild.name} "
        f"(locked {cooldown_until - now:.0f}s)"
    )


# leafbot-style manual sync: per-guild, instant, run it yourself when you change
# a command. Needs the applications.commands scope on the invite.
@bot.command(name="sync")
async def sync_cmd(ctx: commands.Context):
    if ctx.author.id != OWNER_ID:
        return
    synced = await bot.tree.sync(guild=ctx.guild)
    await ctx.send(f"synced {[c.name for c in synced]}")


@bot.hybrid_command(name="level", description="Show your current level and XP.")
@app_commands.describe(member="Optional member to inspect")
@commands.guild_only()
async def level_cmd(
    ctx: commands.Context, member: Optional[discord.Member] = None
):
    target = member or ctx.author
    xp = db.get_xp(ctx.guild.id, target.id)

    lv = level_for(xp)
    floor = xp_for_level(lv)
    ceil = xp_for_level(lv + 1)
    into = xp - floor
    need = ceil - floor

    bar_len = 10
    filled = round(into / need * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)

    embed = discord.Embed(
        title=f"Level {lv}",
        description=f"`{bar}` {into}/{need} to level {lv + 1}",
        colour=discord.Colour.blurple(),
    )
    embed.add_field(name="Total XP", value=f"{xp:,}", inline=True)
    embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)

    await ctx.send(embed=embed)


if __name__ == "__main__":
    db.init()
    token = os.getenv("TOKEN")
    if not token:
        raise SystemExit("TOKEN not set. Add it to .env")
    bot.run(token)
