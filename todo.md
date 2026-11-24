# rotator — todo

Run: `python src/bot.py` (venv, `TOKEN` in .env) — or `docker compose up -d --build`
DB: `levels.db` at repo root, `DB_PATH` overrides.
Commands are leafbot-style, prefix `r!`: `r!level` + `/level` (hybrid), `r!sync`
(hardcoded `OWNER_ID` in bot.py copies the global slash commands into the current
guild and syncs that guild — instant, run once per guild), no `help`.
XP handler uses `@bot.listen()` so a custom `on_message` doesn't swallow
`process_commands`.

## Open
- [ ] Message Content Intent ON (portal → Bot → Privileged Gateway Intents) — else `on_message` never fires, zero XP
- [ ] `r!sync` once per guild — until then `/level` does not exist, `r!level` always works
      (no re-invite needed: docs say `applications.commands` is automatically included with `bot`)
- [x] `r!sync` returned `synced []` — dpy>=2.7 `tree.sync(guild=)` only uploads commands registered *for that guild*, global ones are skipped (and the empty payload wipes the guild bucket). `r!sync` now copies each global command into `ctx.guild` first.
- [ ] `docker build` never actually run (daemon was off) — build once locally
- [ ] `/leaderboard` — needs `db.top_members(guild_id, limit)`
- [ ] Level-up announcement in channel (compare level before/after grant)
- [ ] Show XP-cooldown remaining on `/level` (`member.xp_cooldown - now` already stored)
