"""Minimal Discord leveling bot. discord.py v2, hybrid commands, per-guild XP."""

import asyncio
import math
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

import db

load_dotenv()

# --- config ---------------------------------------------------------------------------

OWNER_ID = 520293520418930690

XP_MIN, XP_MAX = 15, 20
COOLDOWN_MIN_SECS, COOLDOWN_MAX_SECS = 25, 35

XP_BASE = 50.0  # cost of level 2
XP_GROWTH = 1.25

BAR_LEN = 10
BAR_FULL, BAR_EMPTY = "🟩", "⬛"
EMBED_COLOR = discord.Colour(0xFF4023)

ADMIN = "[ADMIN]"  # description prefix for admin-only slash commands
GIVEAWAY_JOIN_ID = "ra:giveaway:join"
GIVEAWAY_MINUTES_DEFAULT, GIVEAWAY_MINUTES_MAX = 10, 24 * 60
GIVEAWAY_WINNERS_MAX = 10

LEVEL_ROLES: dict[int, int | str] = {
    1: 1574741880841834616,
    2: 1574741906045280256,
    3: 1574741924709924946,
}

# --- bot ------------------------------------------------------------------------------

intents = discord.Intents.default()
# needs the Message Content Intent toggle in the dev portal too, else no XP ever.
intents.message_content = True

bot = commands.Bot(command_prefix="r!", intents=intents)
bot.remove_command("help")


# --- XP curve -------------------------------------------------------------------------

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


# --- members & roles ------------------------------------------------------------------

async def resolve_member(guild: discord.Guild, member_id: int) -> Optional[discord.Member]:
    """Cache first, then REST. Intents.members is off, so the cache is mostly empty."""
    member = guild.get_member(member_id)
    if member:
        return member
    try:
        return await guild.fetch_member(member_id)
    except discord.HTTPException:
        return None


def _find_role(guild: discord.Guild, spec: int | str) -> Optional[discord.Role]:
    if isinstance(spec, int):
        return guild.get_role(spec)
    return discord.utils.get(guild.roles, name=spec)


async def sync_level_role(member: discord.Member, level: int) -> bool:
    """Apply the single highest role for `level`, drop the other level roles."""
    if not LEVEL_ROLES:
        return False

    guild = member.guild
    top = guild.me.top_role if guild.me else None
    managed: list[discord.Role] = []
    target: Optional[discord.Role] = None
    for threshold, spec in sorted(LEVEL_ROLES.items()):
        role = _find_role(guild, spec)
        if role is None or role.is_default() or (top and role >= top):
            continue
        managed.append(role)
        if threshold <= level:
            target = role

    current = [role for role in member.roles if role in managed]
    if current == ([target] if target else []):
        return False

    roles = [role for role in member.roles if role not in managed]
    if target:
        roles.append(target)
    roles.sort(key=lambda role: role.position, reverse=True)
    try:
        await member.edit(roles=roles, reason=f"rotator: level {level}")
    except discord.Forbidden as exc:
        print(f"role sync blocked for {member}: {exc}")
        return False
    return True


# --- events ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    # giveaways survive restarts: re-arm the deadline for everything still open.
    for giveaway in db.active_giveaways():
        schedule_giveaway(giveaway)


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
        steps = new_lv - old_lv
        bonus = f" (+{steps} levels)" if steps > 1 else ""
        try:
            await message.channel.send(
                f"🎉 {message.author.mention} reached **level {new_lv}**{bonus}"
            )
        except discord.Forbidden:
            pass
    await sync_level_role(message.author, new_lv)

    print(f"+{gained} xp -> {message.author} in {message.guild.name} (lv {new_lv})")


# --- owner commands -------------------------------------------------------------------

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


# Re-apply level roles: one member, or everyone with XP on this server.
# Goes through the XP table + REST, so it works without the members intent.
@bot.command(name="roles")
@commands.guild_only()
async def roles_cmd(ctx: commands.Context, *, target: Optional[discord.Member] = None):
    if ctx.author.id != OWNER_ID:
        return

    if target:
        pairs = [(target, db.get_xp(ctx.guild.id, target.id))]
    else:
        pairs = []
        for row in db.top_members(ctx.guild.id, 1000):
            member = await resolve_member(ctx.guild, row.member_id)
            if member:
                pairs.append((member, row.xp))

    changed = 0
    for member, xp in pairs:
        changed += await sync_level_role(member, level_for(xp))

    configured = [_find_role(ctx.guild, spec) for spec in LEVEL_ROLES.values()]
    missing = [
        str(spec) for spec, role in zip(LEVEL_ROLES.values(), configured) if role is None
    ]
    note = f" | no such role: {', '.join(missing)}" if missing else ""
    await ctx.send(
        f"checked {len(pairs)} members, updated {changed} "
        f"(roles: {sorted(LEVEL_ROLES.items())}){note}"
    )


# --- giveaways ------------------------------------------------------------------------
# One persistent View serves every giveaway: the button only carries a fixed
# custom_id, all state (entries, deadline, ended) lives in the db and is keyed by
# message id. Nothing here pings anyone until finish_giveaway() runs.

giveaway_tasks: dict[int, asyncio.Task] = {}


def giveaway_embed(giveaway: db.Giveaway, entries: int) -> discord.Embed:
    ends = datetime.fromtimestamp(giveaway.ends_at, tz=timezone.utc)
    stamp = int(giveaway.ends_at)
    embed = discord.Embed(
        title="🎁 Giveaway ended" if giveaway.ended else "🎁 Giveaway",
        description=(
            f"**{giveaway.prize}**\n\n"
            + ("No more entries." if giveaway.ended else "Hit **Join!** below to enter.")
        ),
        colour=EMBED_COLOR,
        timestamp=ends,
    )
    embed.add_field(name="Ends", value=f"<t:{stamp}:R>\n<t:{stamp}:F>", inline=False)
    embed.add_field(name="Entries", value=str(entries), inline=True)
    embed.add_field(name="Winners", value=str(giveaway.winners), inline=True)
    # embed mentions never notify, so the host stays unpinged while entries run.
    embed.add_field(name="Host", value=f"<@{giveaway.host_id}>", inline=True)
    return embed


class GiveawayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # persistent: no per-click timeout

    @discord.ui.button(
        label="Join!", style=discord.ButtonStyle.danger, custom_id=GIVEAWAY_JOIN_ID
    )
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway = db.get_giveaway_by_message(interaction.message.id)
        if giveaway is None or giveaway.ended or giveaway.ends_at <= time.time():
            await interaction.response.send_message(
                "⌛ This giveaway is over.", ephemeral=True
            )
            return

        joined = db.toggle_entry(giveaway.id, interaction.user.id)
        total = db.entry_count(giveaway.id)
        try:
            await interaction.message.edit(embed=giveaway_embed(giveaway, total))
        except discord.HTTPException:
            pass  # the count will be right on the next click / at the end
        await interaction.response.send_message(
            "🎉 You're in!" if joined else "↩️ Entry removed.", ephemeral=True
        )


bot.add_view(GiveawayView())


def schedule_giveaway(giveaway: db.Giveaway) -> None:
    """Arm the deadline. Safe to call twice: on_ready fires on every reconnect."""
    task = giveaway_tasks.get(giveaway.id)
    if task and not task.done():
        return
    delay = max(0.0, giveaway.ends_at - time.time())
    giveaway_tasks[giveaway.id] = bot.loop.create_task(finish_later(giveaway.id, delay))


async def finish_later(giveaway_id: int, delay: float) -> None:
    await asyncio.sleep(delay)
    giveaway_tasks.pop(giveaway_id, None)
    await finish_giveaway(giveaway_id)


async def finish_giveaway(giveaway_id: int) -> None:
    """Close a giveaway, pick winners, and only now mention anyone."""
    if not db.finish_giveaway(giveaway_id):
        return  # another task (e.g. after a restart) already announced this one
    giveaway = db.get_giveaway(giveaway_id)
    if giveaway is None:
        return
    guild = bot.get_guild(giveaway.guild_id)
    channel = bot.get_channel(giveaway.channel_id)
    if guild is None or not isinstance(channel, discord.abc.Messageable):
        print(f"giveaway {giveaway_id}: channel is gone, skipping")
        return

    ids = db.entries(giveaway_id)
    resolved = await asyncio.gather(*(resolve_member(guild, uid) for uid in ids))
    players = [member for member in resolved if member is not None]
    winners = random.sample(players, min(giveaway.winners, len(players)))

    try:
        message = await channel.fetch_message(giveaway.message_id)
        await message.edit(embed=giveaway_embed(giveaway, len(ids)), view=None)
    except discord.HTTPException:
        print(f"giveaway {giveaway_id}: could not edit the giveaway message")

    host = await resolve_member(guild, giveaway.host_id)
    host_text = host.mention if host else f"<@{giveaway.host_id}>"
    if not winners:
        await channel.send(
            f"😕 No entries for **{giveaway.prize}** — {host_text}, no winner this time."
        )
        return
    won = " ".join(member.mention for member in winners)
    await channel.send(f"🎉 {won} won **{giveaway.prize}** — {host_text}, congrats!")


@bot.hybrid_command(
    name="giveaway", description=f"{ADMIN} Start a giveaway with a red Join! button."
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    prize="What the winners get",
    minutes=f"How long it runs (1-{GIVEAWAY_MINUTES_MAX}, default {GIVEAWAY_MINUTES_DEFAULT})",
    winners=f"How many winners (1-{GIVEAWAY_WINNERS_MAX}, default 1)",
)
@commands.guild_only()
async def giveaway_cmd(
    ctx: commands.Context,
    prize: str,
    minutes: int = GIVEAWAY_MINUTES_DEFAULT,
    winners: int = 1,
):
    # default_permissions only hides the command; enforce it for real here.
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("⛔ Administrator only.")
        return

    minutes = max(1, min(int(minutes), GIVEAWAY_MINUTES_MAX))
    winners = max(1, min(int(winners), GIVEAWAY_WINNERS_MAX))
    ends = discord.utils.utcnow() + timedelta(minutes=minutes)

    giveaway_id = db.create_giveaway(
        ctx.guild.id, ctx.channel.id, ctx.author.id, prize[:200], ends.timestamp(), winners
    )
    giveaway = db.get_giveaway(giveaway_id)
    message = await ctx.send(embed=giveaway_embed(giveaway, 0), view=GiveawayView())
    db.set_giveaway_message(giveaway_id, message.id)
    schedule_giveaway(giveaway)


# --- user commands --------------------------------------------------------------------

@bot.hybrid_command(name="level", description="Show your current level and XP.")
@app_commands.describe(member="Optional member to inspect")
@commands.guild_only()
async def level_cmd(
    ctx: commands.Context, member: Optional[discord.Member] = None
):
    def progress_bar(into: int, need: int) -> str:
        filled = max(0, min(BAR_LEN, round(into / need * BAR_LEN)))
        return BAR_FULL * filled + BAR_EMPTY * (BAR_LEN - filled)

    target = member or ctx.author
    row = db.get_member(ctx.guild.id, target.id)
    xp = row.xp if row else 0

    lv = level_for(xp)
    floor, ceil = xp_for_level(lv), xp_for_level(lv + 1)
    into, need = xp - floor, ceil - floor
    rank, _ = db.get_rank(ctx.guild.id, target.id)

    if rank:
        rank_text = f"{target.display_name} is ranked #{rank} · "
    else:
        rank_text = f"{target.display_name} · "

    embed = discord.Embed(title=f"Level {lv}", colour=EMBED_COLOR)
    embed.set_thumbnail(url=target.display_avatar.url)
    if xp:
        embed.description = (
            f"{progress_bar(into, need)} **{into / need:.0%}**\n"
            f"`{into:,}/{need:,}xp` to **level {lv + 1}**!"
        )
    else:
        embed.description = "No xp yet — chat in this server to start."
    embed.set_footer(text=f"{rank_text}{xp:,}xp total")

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
    resolved = await asyncio.gather(
        *(resolve_member(ctx.guild, row.member_id) for row in rows)
    )
    for pos, (row, member) in enumerate(zip(rows, resolved), 1):
        name = (member.display_name if member else "ex-member")[:20]
        lines.append(f"`{pos:>2}` **{name}** - lv{level_for(row.xp)} · `{row.xp:,}xp`")

    rank, _ = db.get_rank(ctx.guild.id, ctx.author.id)
    own_lv = level_for(db.get_xp(ctx.guild.id, ctx.author.id))

    own_rank = f"ranked **#{rank}**" if rank else "unranked"
    you = f"**You** are {own_rank} at lv{own_lv}."

    embed = discord.Embed(
        title="Leaderboard",
        description="\n".join(lines) + f"\n\n{you}",
        colour=EMBED_COLOR,
    )

    await ctx.send(embed=embed)


# --- tuning CLI -----------------------------------------------------------------------

def level_table(top: int = 50) -> None:
    """Tuning aid: `python src/bot.py table`.

    msgs = total XP / mean XP per message; hours assumes back-to-back messaging at
    the mean cooldown, i.e. the fastest a single user could possibly climb.
    """
    avg_xp = (XP_MIN + XP_MAX) / 2
    avg_cooldown = (COOLDOWN_MIN_SECS + COOLDOWN_MAX_SECS) / 2

    def duration(hours: float) -> str:
        return f"{hours * 60:>5.0f}m" if hours < 1 else f"{hours:>5.1f}h"

    print(f"avg {avg_xp:g} xp/msg, {avg_cooldown:g}s cooldown -> {3600 / avg_cooldown:.0f} msg/h max\n")
    for level in range(1, top + 1):
        total = xp_for_level(level + 1)
        msgs = total / avg_xp
        print(
            f"level {level + 1:>3}  total {total:>8,}  (+{total - xp_for_level(level):>6,})"
            f"  ~{msgs:>7,.0f} msgs  ~{duration(msgs * avg_cooldown / 3600)}"
        )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "table":
        level_table()
        raise SystemExit(0)

    db.init()
    token = os.getenv("TOKEN")
    if not token:
        raise SystemExit("TOKEN not set. Add it to .env")
    bot.run(token)
