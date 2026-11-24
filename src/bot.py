"""Minimal Discord leveling bot. discord.py v2, hybrid commands, per-guild XP."""

import math
import os
import random
import sys
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

import db

load_dotenv()

OWNER_ID = 520293520418930690

XP_MIN, XP_MAX = 15, 20
COOLDOWN_MIN_SECS, COOLDOWN_MAX_SECS = 25, 35

# Level curve: each level costs XP_GROWTH x more than the previous one.
# Closed form of a geometric series, so level_for() is exact, no lookup table.
XP_BASE = 100.0
XP_GROWTH = 1.12

BAR_LEN = 10
BAR_FULL, BAR_EMPTY = "🟩", "⬛"
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def xp_for_level(level: int) -> int:
    """Total XP needed to reach `level`. Level 1 is 0."""
    if level <= 1:
        return 0
    return round(XP_BASE * (XP_GROWTH ** (level - 1) - 1) / (XP_GROWTH - 1))


def level_for(xp: int) -> int:
    """Inverse of xp_for_level: log gives the guess, integer checks fix rounding."""
    if xp < xp_for_level(2):
        return 1
    level = int(math.log(xp * (XP_GROWTH - 1) / XP_BASE + 1, XP_GROWTH)) + 1
    while xp_for_level(level + 1) <= xp:
        level += 1
    while xp_for_level(level) > xp:
        level -= 1
    return level


def level_colour(level: int) -> discord.Colour:
    return discord.Colour.from_hsv((level * 0.08) % 1.0, 0.55, 0.85)


def progress_bar(into: int, need: int) -> str:
    filled = max(0, min(BAR_LEN, round(into / need * BAR_LEN)))
    return BAR_FULL * filled + BAR_EMPTY * (BAR_LEN - filled)


def level_table(top: int = 30) -> None:
    """Tuning aid: `python src/bot.py table`."""
    for level in range(1, top + 1):
        total = xp_for_level(level + 1)
        print(f"level {level + 1:>3}  total {total:>8,}  (+{total - xp_for_level(level):>6,})")


intents = discord.Intents.default()
# needs the Message Content Intent toggle in the dev portal too, else no XP ever.
intents.message_content = True

bot = commands.Bot(command_prefix="r!", intents=intents)
bot.remove_command("help")


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")


# bot.listen, not bot.event: a plain on_message would override Bot.on_message
# and kill every prefix/hybrid command.
@bot.listen()
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    now = time.time()
    member = db.get_member(message.guild.id, message.author.id)
    if member and now < member.xp_cooldown:
        return

    before = member.xp if member else 0
    gained = random.randint(XP_MIN, XP_MAX)
    after = db.add_xp(
        message.guild.id,
        message.author.id,
        gained,
        now + random.randint(COOLDOWN_MIN_SECS, COOLDOWN_MAX_SECS),
    )

    old_lv, new_lv = level_for(before), level_for(after)
    if new_lv > old_lv:
        await announce_level_up(message, old_lv, new_lv)

    print(f"+{gained} xp -> {message.author} in {message.guild.name} (lv {new_lv})")


async def announce_level_up(
    message: discord.Message, old_lv: int, new_lv: int
) -> None:
    steps = new_lv - old_lv
    embed = discord.Embed(
        description=(
            f"{'🎉' * min(steps, 5)} {message.author.mention} reached "
            f"**level {new_lv}**" + (f" (+{steps} levels)" if steps > 1 else "")
        ),
        colour=level_colour(new_lv),
    )
    embed.set_thumbnail(url=message.author.display_avatar.url)
    try:
        await message.channel.send(embed=embed)
    except discord.Forbidden:
        pass


# leafbot-style manual sync, needs the applications.commands scope on the invite.
# dpy >=2.7 gotcha: tree.sync(guild=) only uploads guild-scoped commands, so
# r!sync copies each global command into the guild bucket first.
@bot.command(name="sync")
@commands.guild_only()
async def sync_cmd(ctx: commands.Context):
    if ctx.author.id != OWNER_ID:
        return
    for cmd in bot.tree.get_commands(guild=None):
        bot.tree.add_command(cmd.copy(), guild=ctx.guild, override=True)
    synced = await bot.tree.sync(guild=ctx.guild)
    await ctx.send(f"synced {[c.name for c in synced]} in {ctx.guild.name}")


def cooldown_text(row: Optional[db.Member]) -> str:
    if row is None or row.xp_cooldown <= time.time():
        return "✅ ready"
    return f"<t:{int(row.xp_cooldown)}:R>"


@bot.hybrid_command(name="level", description="Show your current level and XP.")
@app_commands.describe(member="Optional member to inspect")
@commands.guild_only()
async def level_cmd(
    ctx: commands.Context, member: Optional[discord.Member] = None
):
    target = member or ctx.author
    row = db.get_member(ctx.guild.id, target.id)
    xp = row.xp if row else 0

    lv = level_for(xp)
    floor, ceil = xp_for_level(lv), xp_for_level(lv + 1)
    into, need = xp - floor, ceil - floor
    rank, total = db.get_rank(ctx.guild.id, target.id)

    embed = discord.Embed(title=f"⭐ Level {lv}", colour=level_colour(lv))
    embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
    embed.set_thumbnail(url=target.display_avatar.url)
    if xp:
        embed.description = (
            f"{progress_bar(into, need)} **{into / need:.0%}**\n"
            f"`{into:,} / {need:,}` XP to **level {lv + 1}**"
        )
    else:
        embed.description = "No XP yet — chat in this server to start."
    embed.add_field(name="⚡ Total XP", value=f"{xp:,}", inline=True)
    rank_text = f"#{rank} of {total}" if rank else f"unranked / {total}"
    embed.add_field(name="📊 Rank", value=rank_text, inline=True)
    embed.add_field(name="⏳ Next XP", value=cooldown_text(row), inline=True)
    embed.set_footer(text=ctx.guild.name)

    await ctx.send(embed=embed)


@bot.hybrid_command(name="leaderboard", description="Top XP earners on this server.")
@app_commands.describe(limit="How many rows to show (1-20)")
@commands.guild_only()
async def leaderboard_cmd(ctx: commands.Context, limit: int = 10):
    limit = max(1, min(int(limit), 20))
    rows = db.top_members(ctx.guild.id, limit)
    if not rows:
        await ctx.send("No XP recorded on this server yet.")
        return

    lines = []
    for pos, row in enumerate(rows, 1):
        medal = MEDALS.get(pos, f"`{pos:>2}`")
        member = ctx.guild.get_member(row.member_id)
        name = (member.display_name if member else "ex-member")[:20]
        lines.append(f"{medal} **{name}** — lv {level_for(row.xp)} · `{row.xp:,}` xp")

    rank, total = db.get_rank(ctx.guild.id, ctx.author.id)
    own_lv = level_for(db.get_xp(ctx.guild.id, ctx.author.id))

    embed = discord.Embed(
        title=f"🏆 Top {len(rows)} — {ctx.guild.name}",
        description="\n".join(lines),
        colour=level_colour(level_for(rows[0].xp)),
    )
    own_rank = f"#{rank} of {total}" if rank else f"unranked / {total}"
    embed.add_field(name="You", value=f"{own_rank} · lv {own_lv}", inline=False)
    embed.set_footer(text="XP is tracked per server")

    await ctx.send(embed=embed)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "table":
        level_table()
        raise SystemExit(0)

    db.init()
    token = os.getenv("TOKEN")
    if not token:
        raise SystemExit("TOKEN not set. Add it to .env")
    bot.run(token)
