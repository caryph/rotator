# rotator — todo

Run: `python src/bot.py` (venv, `TOKEN` in .env) — or `docker compose up -d --build`
DB: `levels.db` at repo root, `DB_PATH` overrides.
Commands are leafbot-style, prefix `r!`: `r!level`/`/level`, `r!leaderboard`/`/leaderboard` (hybrid),
`r!sync` (hardcoded `OWNER_ID` in bot.py copies the global slash commands into the current
guild and syncs that guild — instant, run once per guild), `r!roles [@user]` (owner-only, prefix
only: re-applies level roles to one member or everyone with XP), no `help`.
Level roles: `LEVEL_ROLES = {threshold: "role name" or role_id}` — highest matching threshold
wins, the other level roles get removed (one at a time). Needs Manage Roles + the bot's role
above them; missing role names are reported by `r!roles`. Synced on every XP grant (local
compare, API call only when the role set actually differs), so a `lvl 1` role lands on the
first message.
Intents: only `message_content` is enabled — `members` stays off, so member lookups go through
`resolve_member` (cache, then REST `fetch_member`). No privileged member cache needed.
XP handler uses `@bot.listen()` so a custom `on_message` doesn't swallow
`process_commands`. Levels are never stored — only total XP, level is derived,
so re-balancing the curve is free (edit `XP_BASE` / `XP_GROWTH`, restart).
Curve: cumulative geometric `xp_for_level(L) = XP_BASE * (G^(L-1) - 1) / (G - 1)`,
G=1.12 → each level costs 12% more than the previous. L10@1,478 · L20@6,344 ·
L30@21,458 · L50@214,198 XP. Dump the table with `python src/bot.py table`.

## Open
- [ ] Message Content Intent ON (portal → Bot → Privileged Gateway Intents) — else `on_message` never fires, zero XP
- [ ] `r!sync` once per guild — until then `/level` and `/leaderboard` do not exist, `r!level` always works
      (no re-invite needed: docs say `applications.commands` is automatically included with `bot`)
- [x] `r!sync` returned `synced []` — dpy>=2.7 `tree.sync(guild=)` only uploads commands registered *for that guild*, global ones are skipped (and the empty payload wipes the guild bucket). `r!sync` now copies each global command into `ctx.guild` first.
- [ ] `docker build` never actually run (daemon was off) — build once locally
- [x] `/leaderboard` — `db.top_members(guild_id, limit)` + `db.get_rank`, medals 🥇🥈🥉, own rank in a field
- [x] Level-up announcement in channel (`db.add_xp` RETURNING xp, compare level before/after, embed with 🎉)
- [x] Show XP-cooldown remaining on `/level` (`<t:...:R>` from `member.xp_cooldown`)
- [ ] Tune `XP_GROWTH` once real chat volume is visible (1.12 = gentle, 1.2 = grindy)
- [ ] Create the `LEVEL_ROLES` role names in the server (currently `lvl 1/5/10/20/30`) and give the bot Manage Roles — then `r!roles` to backfill
- [x] Leaderboard showed `ex-member` for present members — `intents.default()` has `members=False`, `guild.get_member()` missed; now falls back to REST `fetch_member`
