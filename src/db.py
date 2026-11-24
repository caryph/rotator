"""All sqlite access lives here. bot.py never touches sqlite directly.

The db file defaults to levels.db in the project root; the DB_PATH env var
overrides it (Docker points that at a volume).
"""

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_DEFAULT_DB = Path(__file__).resolve().parent.parent / "levels.db"
DB_PATH = Path(os.getenv("DB_PATH", str(_DEFAULT_DB)))

_conn: Optional[sqlite3.Connection] = None


@dataclass
class Member:
    guild_id: int
    member_id: int
    xp: int
    xp_cooldown: float  # unix ts of next allowed xp grant


@dataclass
class Giveaway:
    id: int
    guild_id: int
    channel_id: int
    message_id: int
    host_id: int
    prize: str
    ends_at: float  # unix ts the Join! button stops working
    winners: int
    ended: bool


def init(path: Path | str = DB_PATH) -> None:
    """Open connection and create schema. Must be called before use."""
    global _conn
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(path)
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS members (
            guild_id    INTEGER NOT NULL,
            member_id   INTEGER NOT NULL,
            xp          INTEGER NOT NULL DEFAULT 0,
            xp_cooldown REAL    NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, member_id)
        )
        """
    )
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS giveaways (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id   INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL DEFAULT 0,
            host_id    INTEGER NOT NULL,
            prize      TEXT    NOT NULL,
            ends_at    REAL    NOT NULL,
            winners    INTEGER NOT NULL DEFAULT 1,
            ended      INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS giveaway_entries (
            giveaway_id INTEGER NOT NULL,
            user_id     INTEGER NOT NULL,
            PRIMARY KEY (giveaway_id, user_id)
        )
        """
    )
    _conn.commit()


def _db() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("db.init() was not called")
    return _conn


def get_member(guild_id: int, member_id: int) -> Optional[Member]:
    row = _db().execute(
        "SELECT guild_id, member_id, xp, xp_cooldown FROM members "
        "WHERE guild_id = ? AND member_id = ?",
        (guild_id, member_id),
    ).fetchone()
    if row is None:
        return None
    return Member(*row)


def get_xp(guild_id: int, member_id: int) -> int:
    member = get_member(guild_id, member_id)
    return member.xp if member else 0


def add_xp(guild_id: int, member_id: int, amount: int, cooldown_until: float) -> int:
    """Insert-or-update in one statement — no read-modify-write race. Returns new XP."""
    row = _db().execute(
        """
        INSERT INTO members (guild_id, member_id, xp, xp_cooldown) VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id, member_id) DO UPDATE
            SET xp = xp + excluded.xp,
                xp_cooldown = excluded.xp_cooldown
        RETURNING xp
        """,
        (guild_id, member_id, amount, cooldown_until),
    ).fetchone()
    _db().commit()
    return row[0]


def top_members(guild_id: int, limit: int = 10, offset: int = 0) -> list[Member]:
    rows = _db().execute(
        "SELECT guild_id, member_id, xp, xp_cooldown FROM members "
        "WHERE guild_id = ? ORDER BY xp DESC, member_id LIMIT ? OFFSET ?",
        (guild_id, limit, offset),
    ).fetchall()
    return [Member(*row) for row in rows]


# --- giveaways ------------------------------------------------------------------------

_GIVEAWAY_COLS = (
    "id, guild_id, channel_id, message_id, host_id, prize, ends_at, winners, ended"
)


def _giveaway(row: Optional[tuple]) -> Optional[Giveaway]:
    return None if row is None else Giveaway(*row[:8], bool(row[8]))


def create_giveaway(
    guild_id: int,
    channel_id: int,
    host_id: int,
    prize: str,
    ends_at: float,
    winners: int,
) -> int:
    """Row is created before the message exists, hence message_id 0 until the send."""
    row = _db().execute(
        "INSERT INTO giveaways (guild_id, channel_id, host_id, prize, ends_at, winners) "
        "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
        (guild_id, channel_id, host_id, prize, ends_at, winners),
    ).fetchone()
    _db().commit()
    return row[0]


def set_giveaway_message(giveaway_id: int, message_id: int) -> None:
    _db().execute(
        "UPDATE giveaways SET message_id = ? WHERE id = ?", (message_id, giveaway_id)
    )
    _db().commit()


def get_giveaway(giveaway_id: int) -> Optional[Giveaway]:
    row = _db().execute(
        f"SELECT {_GIVEAWAY_COLS} FROM giveaways WHERE id = ?", (giveaway_id,)
    ).fetchone()
    return _giveaway(row)


def get_giveaway_by_message(message_id: int) -> Optional[Giveaway]:
    row = _db().execute(
        f"SELECT {_GIVEAWAY_COLS} FROM giveaways WHERE message_id = ?", (message_id,)
    ).fetchone()
    return _giveaway(row)


def active_giveaways() -> list[Giveaway]:
    rows = _db().execute(
        f"SELECT {_GIVEAWAY_COLS} FROM giveaways WHERE ended = 0"
    ).fetchall()
    return [_giveaway(row) for row in rows]


def finish_giveaway(giveaway_id: int) -> bool:
    """Flip ended 0 -> 1. True only for the caller that actually flipped it, so a
    restart re-scheduling an old giveaway can never announce it twice."""
    cur = _db().execute(
        "UPDATE giveaways SET ended = 1 WHERE id = ? AND ended = 0", (giveaway_id,)
    )
    _db().commit()
    return cur.rowcount == 1


def toggle_entry(giveaway_id: int, member_id: int) -> bool:
    """Join or leave. True means the member is in now."""
    inside = _db().execute(
        "SELECT 1 FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
        (giveaway_id, member_id),
    ).fetchone()
    if inside:
        _db().execute(
            "DELETE FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
            (giveaway_id, member_id),
        )
    else:
        _db().execute(
            "INSERT INTO giveaway_entries (giveaway_id, user_id) VALUES (?, ?)",
            (giveaway_id, member_id),
        )
    _db().commit()
    return inside is None


def entries(giveaway_id: int) -> list[int]:
    rows = _db().execute(
        "SELECT user_id FROM giveaway_entries WHERE giveaway_id = ? ORDER BY user_id",
        (giveaway_id,),
    ).fetchall()
    return [row[0] for row in rows]


def entry_count(giveaway_id: int) -> int:
    return _db().execute(
        "SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,)
    ).fetchone()[0]


def get_rank(guild_id: int, member_id: int) -> tuple[int, int]:
    """(1-based rank, members tracked). Rank 0 when the member has no XP row."""
    total = _db().execute(
        "SELECT COUNT(*) FROM members WHERE guild_id = ?", (guild_id,)
    ).fetchone()[0]
    xp = get_xp(guild_id, member_id)
    if not xp:
        return 0, total
    better = _db().execute(
        "SELECT COUNT(*) FROM members WHERE guild_id = ? AND xp > ?", (guild_id, xp)
    ).fetchone()[0]
    return better + 1, total
