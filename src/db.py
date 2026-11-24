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


def add_xp(guild_id: int, member_id: int, amount: int, cooldown_until: float) -> None:
    """Insert-or-update in one statement — no read-modify-write race."""
    _db().execute(
        """
        INSERT INTO members (guild_id, member_id, xp, xp_cooldown) VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id, member_id) DO UPDATE
            SET xp = xp + excluded.xp,
                xp_cooldown = excluded.xp_cooldown
        """,
        (guild_id, member_id, amount, cooldown_until),
    )
    _db().commit()
