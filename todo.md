# rotator — todo

## Done
- [x] `src/bot.py` (bot) + `src/db.py` (all sqlite access)
- [x] sqlite `members(guild_id, member_id, xp, xp_cooldown)`, PK `(guild_id, member_id)`
- [x] XP is **per-guild**. Verified isolation + upsert accumulation in isolation test
- [x] `on_message`: +15-20 xp, cooldown `now + randint(25,35)`s
- [x] `/level` — embed with level, total xp, progress bar
- [x] Level curve: `level = isqrt(xp // 50) + 1`, `xp_for_level(L) = (L-1)^2 * 50`
- [x] `db.init()` auto-creates parent dirs (sqlite won't). `DB_PATH` env override.
- [x] Docker: `Dockerfile` (non-root, deps layer cached) + `docker-compose.yml`
      + named volume `rotator-data` at `/app/data`
- [x] Comment cleanup: 20 inline comments -> 5. Units moved into names
      (`CD_MIN/CD_MAX` -> `COOLDOWN_MIN_SECS/COOLDOWN_MAX_SECS`), level-curve table
      moved into `xp_for_level` docstring
- [x] Import-checked against real discord.py — `/level` registers, curve + cooldown
      constants resolve. `.venv` created, deps installed.

## Run
Local:
```bash
source .venv/bin/activate   # or: python3 -m venv .venv && pip install -r requirements.txt
python src/bot.py           # levels.db -> project root
```
Docker:
```bash
docker compose up -d --build    # needs TOKEN in .env or exported
```
Portainer: Stack form -> paste `docker-compose.yml` -> add `TOKEN` under
Environment variables. `docker compose config` validates clean.
**`docker build` itself unverified** (daemon was not running) — run it once locally first.

## Open
- [ ] **Enable Message Content Intent** in dev portal → Bot → Privileged Gateway
      Intents. Without it `on_message` never fires → zero XP. Most likely first bug.
- [ ] Invite bot with `scope=bot` + `applications.commands`
      (URL: `https://discord.com/api/oauth2/authorize?client_id=<ID>&permissions=277025508352&scope=bot%20applications.commands`)
- [ ] Command sync currently **per-guild on startup** (instant). Switch to
      `await bot.tree.sync()` (global) for production — global takes up to ~1h to appear.

## Later ideas
- [ ] No container healthcheck — bot exposes no HTTP endpoint, so there is nothing
      to probe. If wanted: write a heartbeat file from a `tasks.loop` and check mtime.
- [ ] For registry-based deploys, build + push (`ghcr.io/<you>/rotator`) and swap
      `build:` for `image:` in compose. Portainer then pulls instead of building.
- [ ] Bind-mount alternative for `rotator-data`: host dir must be chown'd to uid 10001
      (named volumes inherit ownership from the image, bind mounts do not).
- [ ] Level-up announcement in channel (needs to compare level before/after grant)
- [ ] `/leaderboard` — top 10 by xp. Needs new `db.top_members(guild_id, limit)`
- [ ] Role rewards at level thresholds
- [ ] Cooldown is silently swallowed. Maybe show remaining time on `/level`
      (`member.xp_cooldown - now` is already stored)
- [ ] Level curve currently lives in `bot.py`. If it grows (multipliers, role bonuses)
      move to `src/levels.py` — `db.py` should stay pure storage
- [ ] Blocking sqlite calls on event loop — fine now, revisit if guild count grows
      (`aiosqlite` or `asyncio.to_thread`)
