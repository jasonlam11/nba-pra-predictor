"""
Free ESPN public JSON feeds: today's schedule and the league injury report.

No API key, no rate limit, and -- unlike stats.nba.com -- these are reachable
from datacenter IPs, so the daily job can run on GitHub Actions. Only the job
calls these; the request path never does.

The endpoints are undocumented and can change shape without notice, so every
fetch fails soft: a missing schedule or injury feed degrades that one section
of the snapshot rather than aborting the build.
"""

import json
import os
from datetime import datetime, timedelta

import requests

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"

HERE = os.path.dirname(os.path.abspath(__file__))
TEAMS_PATH = os.path.join(HERE, "..", "data", "teams.json")

# Deliberately NO User-Agent override.
#
# Counterintuitively, ESPN 403s a spoofed browser User-Agent ("Mozilla/5.0 ...")
# while serving 200 to requests' own "python-requests/x.y" default: a browser UA
# arriving without a browser TLS fingerprint reads as a bot. The old injury
# fetch in main.py spoofed Mozilla and would fail the same way today.
#
# Verified 2026-09-29: default UA -> 200, spoofed Chrome UA -> 403.


def _get_json(url, timeout=15):
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def load_teams() -> dict:
    with open(TEAMS_PATH) as fh:
        return json.load(fh)


def _espn_index(teams: dict) -> dict:
    """{espn_team_id: team record} for translating scoreboard competitors."""
    return {t["espn_team_id"]: t for t in teams.values()}


def fetch_games(date: datetime = None) -> list:
    """
    Today's games in the exact shape the existing /games/today endpoint returns,
    so the frontend's Game/TeamInfo models need no change.

    Team ids are nba_api ids, not ESPN ids, because GameCard links straight to
    /teams/{id}/players.
    """
    teams = load_teams()
    by_espn = _espn_index(teams)

    url = SCOREBOARD_URL
    if date is not None:
        url += f"?dates={date.strftime('%Y%m%d')}"

    try:
        raw = _get_json(url)
    except Exception as e:
        print(f"  scoreboard unavailable ({type(e).__name__}: {e})")
        return []

    games = []
    for event in raw.get("events", []):
        comps = event.get("competitions") or []
        if not comps:
            continue
        competitors = comps[0].get("competitors", [])

        sides = {}
        for c in competitors:
            espn_id = int(c.get("team", {}).get("id", 0))
            team = by_espn.get(espn_id)
            if team is None:
                continue
            records = c.get("records") or []
            sides[c.get("homeAway")] = {
                "id": team["nba_team_id"],
                "name": team["nickname"],
                "city": team["city"],
                "abbreviation": team["tricode"],
                "record": (records[0].get("summary") if records else "0-0") or "0-0",
            }

        if "home" not in sides or "away" not in sides:
            continue

        games.append({
            "game_id": str(event.get("id", "")),
            "status": (event.get("status", {}).get("type", {}).get("shortDetail") or ""),
            "start_time": event.get("date", ""),
            "home_team": sides["home"],
            "away_team": sides["away"],
        })
    return games


def fetch_upcoming(days: int = 2) -> list:
    """Today plus the next `days-1` days, so a prediction always has a matchup."""
    out = []
    seen = set()
    for offset in range(days):
        for g in fetch_games(datetime.now() + timedelta(days=offset)):
            if g["game_id"] not in seen:
                seen.add(g["game_id"])
                out.append(g)
    return out


def fetch_injuries() -> dict:
    """
    {player_name_lower: {status, description}} — same shape and same filtering
    as the old in-process fetch in main.py, so /injuries is unchanged.
    """
    try:
        raw = _get_json(INJURIES_URL)
    except Exception as e:
        print(f"  injuries unavailable ({type(e).__name__}: {e})")
        return {}

    result = {}
    for team_entry in raw.get("injuries", []):
        for inj in team_entry.get("injuries", []):
            name = inj.get("athlete", {}).get("displayName", "")
            status = inj.get("status", "")
            # Only real injury statuses — "Active" means available.
            if not name or not status or status.lower() in ("active", ""):
                continue
            details = inj.get("details") or {}
            result[name.lower()] = {
                "status": status,
                "description": details.get("type") or status,
            }
    return result
