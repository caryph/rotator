# rotator — todo

Run: `python src/bot.py` (venv, `TOKEN` in .env) — or `docker compose up -d --build`
DB: `levels.db` at repo root, `DB_PATH` overrides.
Commands are leafbot-style, prefix `r!`: `r!level` + `/level` (hybrid), `r!sync`
(hardcoded `OWNER_ID` in bot.py syncs the slash tree to the current guild), no `help`.
XP handler uses `@bot.listen()` so a custom `on_message` doesn't swallow
`process_commands`.

## Open
- [ ] Message Content Intent ON (portal → Bot → Privileged Gateway Intents) — else `on_message` never fires, zero XP
- [ ] Re-invite with `scope=bot applications.commands`, then `r!sync` once per guild — until then `/level` does not exist, `r!level` always works
- [ ] `docker build` never actually run (daemon was off) — build once locally
- [ ] `/leaderboard` — needs `db.top_members(guild_id, limit)`
- [ ] Level-up announcement in channel (compare level before/after grant)
- [ ] Show XP-cooldown remaining on `/level` (`member.xp_cooldown - now` already stored)
