"""
Maps ESPN athlete ids (used by the bulk box scores) to nba_api player ids
(used by the frontend).

The nba_api id stays canonical on purpose: pinned players in localStorage, the
/compare page and roster links all key off it, so changing the primary id would
force a client-side data migration for no benefit.

Matching is by normalized name against nba_api's *full* static list (~5,100
names), not the active-only list. That distinction matters: the active list is
bundled with the package and goes stale between releases, so matching against it
drops exactly the rookies a predictor most wants. Measured on 2025-26:

    full list    572/592 matched (96.6%);  505/511 for players with >=10 games
    active list  457/571 matched (80.0%)

Players who still do not match get a synthetic id so they remain usable rather
than disappearing from the app.
"""

import json
import os
import re
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "data")
OVERRIDES_PATH = os.path.join(DATA_DIR, "id_overrides.json")

# ESPN ids are ~7 digits; this offset cannot collide with a real nba_api id
# (those are <= ~1.7M) and stays well inside a 32-bit int for the frontend.
SYNTHETIC_ID_BASE = 900_000_000

_SUFFIXES = (" jr", " sr", " ii", " iii", " iv", " v")


def normalize_name(name: str) -> str:
    """Casefold, strip accents and punctuation, drop generational suffixes."""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z ]", "", s.lower())
    s = " ".join(s.split())
    for suf in _SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)]
            break
    return " ".join(s.split())


def espn_key(espn_id) -> str:
    """
    Canonical dict key for an ESPN athlete id.

    The bulk parquet stores athlete_id as float64, so a bare str() yields
    "4066648.0" and quietly fails to match "4066648". Everything that keys off
    an ESPN id goes through here.
    """
    return str(int(float(espn_id)))


def _load_overrides() -> dict:
    if not os.path.exists(OVERRIDES_PATH):
        return {}
    with open(OVERRIDES_PATH) as fh:
        return {str(k): int(v) for k, v in json.load(fh).items()}


def _nba_static_index():
    """{normalized_name: player_id}, preferring active players on collision."""
    from nba_api.stats.static import players as nba_players

    index, collisions = {}, set()
    for p in nba_players.get_players():
        key = normalize_name(p["full_name"])
        if key in index:
            collisions.add(key)
            # An active player is far more likely to be the one in a current
            # box score than a retired namesake.
            if not p.get("is_active"):
                continue
        index[key] = p["id"]
    return index, collisions


def build_id_map(athletes) -> dict:
    """
    `athletes` is an iterable of (espn_id, display_name).

    Returns {str(espn_id): {"player_id": int, "name": str, "source": str}}
    where source is one of override / nba_static / synthetic.
    """
    overrides = _load_overrides()
    index, collisions = _nba_static_index()

    out = {}
    for espn_id, name in athletes:
        key_id = espn_key(espn_id)
        if key_id in overrides:
            out[key_id] = {"player_id": overrides[key_id], "name": name, "source": "override"}
            continue

        key = normalize_name(name)
        if key in index and key not in collisions:
            out[key_id] = {"player_id": index[key], "name": name, "source": "nba_static"}
        elif key in index:
            # Ambiguous name — take the active-preferred hit but flag it so a
            # wrong guess is visible in the committed map rather than invisible.
            out[key_id] = {"player_id": index[key], "name": name, "source": "nba_static_ambiguous"}
        else:
            out[key_id] = {
                "player_id": SYNTHETIC_ID_BASE + int(espn_id),
                "name": name,
                "source": "synthetic",
            }
    return out


def match_rate(id_map: dict, espn_ids=None) -> float:
    """Share of entries resolved to a real nba_api id (not synthetic)."""
    items = id_map.values() if espn_ids is None else [
        id_map[espn_key(i)] for i in espn_ids if espn_key(i) in id_map
    ]
    items = list(items)
    if not items:
        return 0.0
    return sum(1 for v in items if v["source"] != "synthetic") / len(items)
