"""
Read-only accessor for the daily snapshot.

The API serves every endpoint from this one SQLite file and makes no upstream
calls, which is the whole point: stats.nba.com blocks the datacenter IPs that
free hosts run on, so anything reaching upstream at request time cannot be
deployed for free. Rebuilding the file is `scripts/build_snapshot.py`.

Resolution order at startup:
  1. SNAPSHOT_URL  -- download to SNAPSHOT_DIR (default /tmp, writable on hosts
                      whose app directory is read-only)
  2. the file committed/baked at backend/data/snapshot.db
"""

import json
import os
import shutil
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(HERE, "..", "data", "snapshot.db")
SNAPSHOT_URL = os.getenv("SNAPSHOT_URL", "").strip()
SNAPSHOT_DIR = os.getenv("SNAPSHOT_DIR", os.path.join(tempfile.gettempdir(), "nba-snapshot"))
EXPECTED_SCHEMA_VERSION = 1
STALE_AFTER_HOURS = float(os.getenv("SNAPSHOT_STALE_HOURS", "36"))

# One connection PER THREAD, not one shared connection.
#
# FastAPI runs sync endpoints in a threadpool, so a single shared
# sqlite3.Connection gets used concurrently. Even with check_same_thread=False
# that is not safe: concurrent statements on one connection corrupt its state
# and surface as "file is not a database" on a perfectly good file. Observed
# when a page load fired /injuries and /teams/defense-ratings at the same time.
#
# `_generation` lets a hot-swap invalidate every thread's cached connection
# without touching the other threads directly.
_local = threading.local()
_path = None
_generation = 0
_meta = {}
_lock = threading.Lock()


class SnapshotUnavailable(RuntimeError):
    pass


def _open(path: str) -> sqlite3.Connection:
    # immutable=1 means no -wal/-shm sidecars are created, so the containing
    # directory never needs to be writable. Safe here because the builder swaps
    # a new file in atomically rather than mutating this one in place.
    uri = f"file:{os.path.abspath(path)}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _download(url: str) -> str:
    import requests

    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    dest = os.path.join(SNAPSHOT_DIR, "snapshot.db")
    tmp = dest + ".tmp"
    print(f"Downloading snapshot from {url} ...")
    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as fh:
            shutil.copyfileobj(resp.raw, fh)
    os.replace(tmp, dest)
    return dest


def load(path: str = None) -> dict:
    """Open a snapshot and return its meta. Safe to call again to hot-swap."""
    global _path, _meta, _generation

    if path is None:
        path = None
        if SNAPSHOT_URL:
            try:
                path = _download(SNAPSHOT_URL)
            except Exception as e:
                print(f"Snapshot download failed ({type(e).__name__}: {e}); "
                      f"falling back to local copy")
        if path is None:
            path = DEFAULT_PATH

    if not os.path.exists(path):
        raise SnapshotUnavailable(
            f"No snapshot at {path}. Run: python scripts/build_snapshot.py"
        )

    probe = _open(path)
    try:
        meta = {r["key"]: r["value"] for r in probe.execute("SELECT key, value FROM meta")}
    finally:
        probe.close()

    version = int(meta.get("schema_version", -1))
    if version != EXPECTED_SCHEMA_VERSION:
        raise SnapshotUnavailable(
            f"Snapshot schema v{version} but this build expects "
            f"v{EXPECTED_SCHEMA_VERSION}. Rebuild it."
        )

    with _lock:
        _path = path
        _meta = meta
        _generation += 1

    print(f"Snapshot loaded: {path} (built {meta.get('built_at')}, "
          f"{meta.get('n_predictions')} predictions)")
    return meta


def _db() -> sqlite3.Connection:
    """This thread's connection, opened on first use and after a hot-swap."""
    if _path is None:
        raise SnapshotUnavailable("Snapshot not loaded")

    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "generation", -1) == _generation:
        return conn

    if conn is not None:
        conn.close()
    conn = _open(_path)
    _local.conn = conn
    _local.generation = _generation
    return conn


def meta() -> dict:
    return dict(_meta)


def age_hours():
    built = _meta.get("built_at")
    if not built:
        return None
    try:
        ts = datetime.fromisoformat(built)
    except ValueError:
        return None
    # Snapshots built before built_at carried a timezone are naive, and were
    # written by a UTC runner -- treat them as UTC rather than as local time,
    # which would otherwise report a negative age and never flag staleness.
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds() / 3600


def is_stale() -> bool:
    age = age_hours()
    return age is not None and age > STALE_AFTER_HOURS


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def search_players(query: str, limit: int = 10) -> list:
    """Substring match on name, same semantics the nba_api static search had."""
    q = f"%{query.lower()}%"
    rows = _db().execute(
        """
        SELECT player_id, full_name, first_name, last_name
        FROM players
        WHERE search_name LIKE ?
        ORDER BY
            -- prefix matches first, then the most-played players
            CASE WHEN search_name LIKE ? THEN 0 ELSE 1 END,
            games_played DESC,
            full_name
        LIMIT ?
        """,
        (q, f"{query.lower()}%", limit),
    ).fetchall()
    return [
        {
            "id": r["player_id"],
            "full_name": r["full_name"],
            "first_name": r["first_name"],
            "last_name": r["last_name"],
            "is_active": True,
        }
        for r in rows
    ]


def player_exists(player_id: int) -> bool:
    return _db().execute(
        "SELECT 1 FROM players WHERE player_id = ?", (player_id,)
    ).fetchone() is not None


def get_prediction(player_id: int):
    row = _db().execute(
        "SELECT payload FROM predictions WHERE player_id = ?", (player_id,)
    ).fetchone()
    return json.loads(row["payload"]) if row else None


def get_games(date: str = None) -> list:
    """Games for `date` (YYYY-MM-DD), defaulting to today."""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    rows = _db().execute(
        "SELECT payload FROM games WHERE game_date = ? ORDER BY game_id", (date,)
    ).fetchall()
    return [json.loads(r["payload"]) for r in rows]


def get_upcoming_games(limit: int = 20) -> list:
    rows = _db().execute(
        "SELECT payload FROM games ORDER BY game_date, game_id LIMIT ?", (limit,)
    ).fetchall()
    return [json.loads(r["payload"]) for r in rows]


def get_injuries() -> dict:
    return {
        r["name_lower"]: {"status": r["status"], "description": r["description"]}
        for r in _db().execute("SELECT * FROM injuries")
    }


def get_defense_ratings() -> dict:
    return {
        r["tricode"]: {
            "pts_allowed": r["pts_allowed"], "pts_rank": r["pts_rank"],
            "reb_allowed": r["reb_allowed"], "reb_rank": r["reb_rank"],
            "ast_allowed": r["ast_allowed"], "ast_rank": r["ast_rank"],
            "overall_rank": r["overall_rank"],
        }
        for r in _db().execute("SELECT * FROM team_defense")
    }


def get_roster(team_id: int) -> list:
    rows = _db().execute(
        """
        SELECT player_id, full_name, jersey, position
        FROM players WHERE team_id = ?
        ORDER BY games_played DESC, full_name
        """,
        (team_id,),
    ).fetchall()
    return [
        {"id": r["player_id"], "name": r["full_name"],
         "number": r["jersey"] or "", "position": r["position"] or ""}
        for r in rows
    ]
