"""
Builds the daily snapshot the API serves from.

Everything expensive or blockable happens here, offline from any user request:
download the free bulk box scores, translate them, run the model for every
player, and write one SQLite file. The API then answers requests with indexed
reads and makes no upstream calls at all -- which is what makes free hosting
possible, since stats.nba.com blocks the datacenter IPs those hosts run on.

    python scripts/build_snapshot.py [--out PATH] [--seasons N]

The file is built to a temporary path and swapped into place only after it
passes validation, so a failed or partial run never replaces a good snapshot.
"""

import argparse
import json
import os
import pickle
import sqlite3
import sys
from datetime import datetime, timezone

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

from parquet_source import load_seasons, latest_available_season      # noqa: E402
from espn_adapter import (                                            # noqa: E402
    clean_box_scores, to_nba_gamelog, opponent_defense_history,
    team_absence_history, latest_opponent_ratings,
)
from id_map import build_id_map, match_rate, espn_key                 # noqa: E402
import espn_live                                                      # noqa: E402
from app.predict import (                                             # noqa: E402
    make_prediction,
    _season_averages_from_log,
    _recent_stats_from_log,
    _compute_reasons,
)

SCHEMA_VERSION = 1
DEFAULT_OUT = os.path.join(HERE, "..", "data", "snapshot.db")
MODEL_PATH = os.path.join(HERE, "..", "models", "pra_model.pkl")

MIN_GAMES_FOR_PREDICTION = 10   # engineer_features returns None below this
LOOKAHEAD_DAYS = 8              # far enough to span an off day or the All-Star break

# Validation thresholds. The build aborts rather than publishing a snapshot
# that would quietly serve a degraded app.
MIN_PLAYERS = 400
MIN_PREDICTIONS = 300
MIN_MATCH_RATE = 0.95
SPOT_CHECK_NAMES = ["Nikola Jokic", "Shai Gilgeous-Alexander", "Stephen Curry"]


SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE players (
    player_id    INTEGER PRIMARY KEY,
    espn_id      INTEGER,
    full_name    TEXT NOT NULL,
    first_name   TEXT,
    last_name    TEXT,
    is_active    INTEGER,
    search_name  TEXT NOT NULL,
    team_id      INTEGER,
    team_tricode TEXT,
    jersey       TEXT,
    position     TEXT,
    headshot_url TEXT,
    id_source    TEXT,
    games_played INTEGER
);
CREATE INDEX idx_players_search ON players(search_name);
CREATE INDEX idx_players_team   ON players(team_id);

CREATE TABLE game_logs (
    player_id INTEGER NOT NULL,
    game_id   TEXT NOT NULL,
    game_date TEXT NOT NULL,
    matchup   TEXT,
    wl        TEXT,
    min       REAL,
    pts       INTEGER,
    reb       INTEGER,
    ast       INTEGER,
    PRIMARY KEY (player_id, game_id)
);
CREATE INDEX idx_logs_player_date ON game_logs(player_id, game_date DESC);

CREATE TABLE predictions (
    player_id      INTEGER PRIMARY KEY,
    payload        TEXT NOT NULL,
    last_game_date TEXT,
    total_pra      REAL
);

CREATE TABLE games (
    game_id   TEXT PRIMARY KEY,
    game_date TEXT,
    status    TEXT,
    payload   TEXT NOT NULL
);

CREATE TABLE injuries (
    name_lower  TEXT PRIMARY KEY,
    status      TEXT,
    description TEXT
);

CREATE TABLE team_defense (
    tricode      TEXT PRIMARY KEY,
    team_id      INTEGER,
    pts_allowed  REAL, pts_rank  INTEGER,
    reb_allowed  REAL, reb_rank  INTEGER,
    ast_allowed  REAL, ast_rank  INTEGER,
    overall_rank INTEGER
);
"""


# ---------------------------------------------------------------------------
# Build stages
# ---------------------------------------------------------------------------

def compute_team_defense(clean: pd.DataFrame, teams: dict) -> list:
    """
    Points/rebounds/assists each team allows per game, plus ranks.

    Derived entirely from the box scores already downloaded -- the old
    implementation tried to pull this from stats.nba.com, gave up, and was left
    returning {} forever, which is why the opponent-defense UI never rendered.

    A row's `opponent_team_abbreviation` is who the player played against, so
    summing a game's rows by opponent gives what that opponent conceded.
    """
    per_game = (
        clean.groupby(["opponent_team_abbreviation", "game_id"])[["points", "rebounds", "assists"]]
        .sum()
        .reset_index()
    )
    avg = (
        per_game.groupby("opponent_team_abbreviation")[["points", "rebounds", "assists"]]
        .mean()
        .round(1)
        .reset_index()
        .rename(columns={"opponent_team_abbreviation": "tricode"})
    )

    # Rank 1 = stingiest. The UI reads a high rank as a favourable matchup.
    avg["pts_rank"] = avg["points"].rank(method="min").astype(int)
    avg["reb_rank"] = avg["rebounds"].rank(method="min").astype(int)
    avg["ast_rank"] = avg["assists"].rank(method="min").astype(int)
    avg["overall_rank"] = (
        avg[["pts_rank", "reb_rank", "ast_rank"]].mean(axis=1).rank(method="min").astype(int)
    )

    rows = []
    for r in avg.itertuples():
        team = teams.get(r.tricode)
        rows.append((
            r.tricode,
            team["nba_team_id"] if team else None,
            float(r.points), int(r.pts_rank),
            float(r.rebounds), int(r.reb_rank),
            float(r.assists), int(r.ast_rank),
            int(r.overall_rank),
        ))
    return rows


def expected_minutes(clean: pd.DataFrame) -> dict:
    """{espn_athlete_id: recent average minutes} from each player's last 10 games."""
    d = clean[["athlete_id", "game_date", "minutes"]].copy()
    d["minutes"] = pd.to_numeric(d["minutes"], errors="coerce").fillna(0.0)
    d = d.sort_values("game_date")
    return (
        d.groupby("athlete_id")["minutes"]
        .apply(lambda s: float(s.tail(10).mean()))
        .to_dict()
    )


ABSENT_STATUSES = {"out", "doubtful"}

INJURY_ARCHIVE_DIR = os.path.join(HERE, "..", "data", "injuries")


def archive_injury_report(report: dict, absent_by_team: dict, players: dict,
                          exp_minutes: dict, out_dir: str = None) -> str:
    """
    Append today's injury report to a permanent per-day archive.

    This exists to make one specific measurement possible later. The
    TEAM_MIN_ABSENT feature was trained on who *did not play*, which is only
    knowable after tip-off; in production it is inferred from this report
    instead. How much accuracy that proxy costs cannot be backtested, because
    ESPN serves only the current report and keeps no history.

    So we build the history ourselves. Each day's file records both the raw
    report AND the derived per-team absent minutes actually fed to the model --
    so a future backtest can join logged pre-game state against what really
    happened, without having to reconstruct the feature from scratch.

    Files are named `YYYY-MM-DDTHH.json` in UTC, one per capture rather than one
    per day. The job runs twice daily, and the two captures are not equivalent:
    the morning one is taken ~16 hours before tip-off, the evening one shortly
    before it, by which point questionable players have usually been ruled in or
    out. Collapsing them to one file per day would discard exactly the
    difference worth studying -- how much the report firms up as a game
    approaches, and therefore how much of the absence signal is actually
    knowable at prediction time.

    One immutable file per capture rather than one growing file: git stores a new
    blob for every version of a file it sees, so appending to a single JSONL
    would re-store the entire history daily (~700 MB/year). Separate small files
    cost a few KB each.

    Returns the path written, or None if there was nothing worth recording.
    """
    if not report or not report.get("entries"):
        # Never write an empty day. A failed fetch would otherwise be
        # indistinguishable from "nobody was injured", which is worse than a gap.
        print("      injury archive: skipped (no entries to record)")
        return None

    out_dir = out_dir or INJURY_ARCHIVE_DIR
    os.makedirs(out_dir, exist_ok=True)

    by_espn_name = {}
    for row in players.values():
        by_espn_name[row[2].lower()] = row[1]   # full_name -> espn_id

    entries = []
    for e in report["entries"]:
        espn_id = by_espn_name.get(e["name"].lower())
        entries.append({
            **e,
            "espn_id": int(espn_id) if espn_id is not None else None,
            # Minutes this player had been averaging when the report was taken.
            # Recorded now because it is cheap; recomputing it later means
            # rebuilding rolling averages as of this exact date.
            "expected_minutes": round(float(exp_minutes.get(espn_id, 0.0) or 0.0), 1),
        })

    # UTC, not local time. CI runs at 06:30 UTC while a developer might run this
    # at 21:00 PT the previous calendar day -- using local dates would file two
    # reports for what is effectively the same day, or overwrite the wrong one.
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    slot = now.strftime("%Y-%m-%dT%H")
    payload = {
        "date": day,
        "captured_hour_utc": now.hour,
        "captured_at": now.isoformat(timespec="seconds"),
        "source": "site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries",
        "source_timestamp": report.get("timestamp", ""),
        "absent_statuses": sorted(ABSENT_STATUSES),
        "n_entries": len(entries),
        "entries": entries,
        # The exact feature value the model was given today, keyed by nba_api
        # team id, so a backtest does not have to re-derive it.
        "team_absent_minutes": {
            str(tid): v["minutes"] for tid, v in sorted(absent_by_team.items())
        },
    }

    path = os.path.join(out_dir, f"{slot}.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=1, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, path)
    print(f"      injury archive: {len(entries)} entries -> data/injuries/{slot}.json")
    return path


def absence_from_injuries(players: dict, injuries: dict, exp_minutes: dict) -> dict:
    """
    {nba_team_id: {"minutes": float, "names": [...]}} expected to be missing tonight.

    This is the production stand-in for team_absence_history. Training measures
    absence as "did not play", which is only knowable after tip-off; here the
    injury report has to carry it instead. The two are correlated but not the
    same -- a Questionable player often suits up, and late scratches never
    appear -- so the model sees a noisier version of this feature in production
    than it did in training. Statuses are limited to Out/Doubtful to keep the
    signal conservative rather than inflating absences that do not happen.
    """
    out = {}
    for pid, row in players.items():
        team_id, name, espn_id = row[7], row[2], row[1]
        if team_id is None:
            continue
        info = injuries.get(name.lower())
        if not info or str(info.get("status", "")).lower() not in ABSENT_STATUSES:
            continue
        mins = float(exp_minutes.get(espn_id, 0.0) or 0.0)
        entry = out.setdefault(team_id, {"minutes": 0.0, "names": []})
        entry["minutes"] += mins
        entry["names"].append({"name": name, "status": info.get("status", ""),
                               "minutes": round(mins, 1)})
    for entry in out.values():
        entry["minutes"] = round(entry["minutes"], 1)
        entry["names"].sort(key=lambda x: -x["minutes"])
    return out


def next_game_context(games: list, teams: dict) -> dict:
    """
    {nba_team_id: {"is_home": bool, "game_date": Timestamp, "opponent": tricode}}
    for each team's next scheduled game.

    Without this a prediction inherits IS_HOME / DAYS_REST from the player's
    *previous* game, which is what the old code did.
    """
    out = {}
    for g in sorted(games, key=lambda x: x.get("start_time") or ""):
        try:
            when = pd.to_datetime(g.get("start_time"), utc=True).tz_localize(None)
        except Exception:
            continue
        for side, other in (("home_team", "away_team"), ("away_team", "home_team")):
            tid = g[side]["id"]
            if tid in out:
                continue  # already have this team's *next* game
            out[tid] = {
                "is_home": side == "home_team",
                "game_date": when,
                "opponent": g[other]["abbreviation"],
            }
    return out


def build_players(clean: pd.DataFrame, id_map: dict, teams: dict) -> dict:
    """{player_id: player row tuple}, using each athlete's most recent game."""
    latest = (
        clean.sort_values("game_date")
        .groupby("athlete_id")
        .tail(1)
        .set_index("athlete_id")
    )
    counts = clean.groupby("athlete_id").size()

    rows = {}
    for espn_id, r in latest.iterrows():
        entry = id_map.get(espn_key(espn_id))
        if entry is None:
            continue
        pid = entry["player_id"]
        name = str(r["athlete_display_name"])
        parts = name.split(" ", 1)
        team = teams.get(str(r["team_abbreviation"]))
        rows[pid] = (
            pid,
            int(espn_id),
            name,
            parts[0],
            parts[1] if len(parts) > 1 else "",
            1,
            name.lower(),
            team["nba_team_id"] if team else None,
            str(r["team_abbreviation"]),
            str(r.get("athlete_jersey") or ""),
            str(r.get("athlete_position_abbreviation") or ""),
            str(r.get("athlete_headshot_href") or ""),
            entry["source"],
            int(counts.get(espn_id, 0)),
        )
    return rows


def build_predictions(clean, id_map, players, model_data, ctx_by_team,
                      opp_hist=None, absence_hist=None, absent_by_team=None,
                      opp_latest=None):
    """Run the model once per player and store the exact API payload."""
    pred_rows, log_rows = [], []
    skipped = 0

    for espn_id, group in clean.groupby("athlete_id"):
        entry = id_map.get(espn_key(espn_id))
        if entry is None:
            continue
        pid = entry["player_id"]
        player = players.get(pid)
        if player is None:
            continue

        log = to_nba_gamelog(group, player_id=pid)
        if len(log) < MIN_GAMES_FOR_PREDICTION:
            skipped += 1
            continue
        team_id = player[7]

        for r in log.itertuples():
            log_rows.append((pid, r.Game_ID, r.GAME_DATE, r.MATCHUP, r.WL,
                             float(r.MIN), int(r.PTS), int(r.REB), int(r.AST)))

        season = _season_averages_from_log(log)
        recent_games, last_5_avg = _recent_stats_from_log(log, num_games=5)
        last_20_games, _ = _recent_stats_from_log(log, num_games=20)

        # Context of the game actually being predicted, when we know it.
        next_game = None
        absent = (absent_by_team or {}).get(team_id, {"minutes": 0.0, "names": []})
        ctx = ctx_by_team.get(team_id)
        if ctx is not None:
            last_played = pd.to_datetime(log["GAME_DATE"].iloc[0], format="%b %d, %Y")
            overrides = {"TEAM_MIN_ABSENT": absent["minutes"]}
            # Tonight's opponent, rather than the last team this player faced.
            overrides.update((opp_latest or {}).get(ctx["opponent"], {}))
            next_game = {
                "is_home": ctx["is_home"],
                "days_rest": int(max((ctx["game_date"] - last_played).days, 0)),
                "overrides": overrides,
            }

        prediction = make_prediction(
            log, season, model_data=model_data, next_game=next_game,
            opp_history=opp_hist, absence_history=absence_hist,
        )

        payload = {
            "player": {
                "id": pid,
                "full_name": player[2],
                "first_name": player[3],
                "last_name": player[4],
                "is_active": True,
            },
            "prediction": prediction,
            "recent_games": recent_games,
            "last_20_games": last_20_games,
            "last_5_avg": last_5_avg,
            "season_avg": season,
            "reasons": _compute_reasons(log),
            # Surfaced in the UI: who is out matters to a prop decision whether
            # or not it moves the model much.
            "absent_teammates": absent["names"][:5],
            "absent_minutes": absent["minutes"],
        }
        pred_rows.append((pid, json.dumps(payload), log["GAME_DATE"].iloc[0],
                          float(prediction["total_pra"])))

    return pred_rows, log_rows, skipped


# ---------------------------------------------------------------------------
# Validation + write
# ---------------------------------------------------------------------------

def validate(players, pred_rows, rate, clean, spot_names):
    problems = []
    if len(players) < MIN_PLAYERS:
        problems.append(f"only {len(players)} players (need >= {MIN_PLAYERS})")
    if len(pred_rows) < MIN_PREDICTIONS:
        problems.append(f"only {len(pred_rows)} predictions (need >= {MIN_PREDICTIONS})")
    if rate < MIN_MATCH_RATE:
        problems.append(f"id match rate {rate:.1%} below {MIN_MATCH_RATE:.0%}")

    names = set(clean["athlete_display_name"])
    for n in spot_names:
        if n not in names:
            problems.append(f"spot-check player missing: {n}")

    implausible = [p for p in pred_rows if not (0 < p[3] < 100)]
    if implausible:
        problems.append(f"{len(implausible)} predictions outside 0-100 PRA")
    return problems


def write_db(path, *, players, pred_rows, log_rows, games, injuries, defense, meta):
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)

    conn.executemany("INSERT OR REPLACE INTO players VALUES (%s)" % ",".join("?" * 14),
                     list(players.values()))
    conn.executemany("INSERT OR REPLACE INTO game_logs VALUES (?,?,?,?,?,?,?,?,?)", log_rows)
    conn.executemany("INSERT OR REPLACE INTO predictions VALUES (?,?,?,?)", pred_rows)
    conn.executemany("INSERT OR REPLACE INTO games VALUES (?,?,?,?)", games)
    conn.executemany("INSERT OR REPLACE INTO injuries VALUES (?,?,?)", injuries)
    conn.executemany("INSERT OR REPLACE INTO team_defense VALUES (?,?,?,?,?,?,?,?,?)", defense)
    conn.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)",
                     [(k, str(v)) for k, v in meta.items()])

    conn.commit()
    conn.execute("VACUUM")
    conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--seasons", type=int, default=2,
                    help="how many seasons of history to include")
    ap.add_argument("--no-archive", action="store_true",
                    help="skip writing today's injury report to data/injuries/")
    args = ap.parse_args()

    started = datetime.now()
    print("=" * 62)
    print("Building snapshot")
    print("=" * 62)

    latest = latest_available_season()
    years = list(range(latest - args.seasons + 1, latest + 1))
    print(f"\n[1/7] Bulk box scores for seasons {years}")
    raw = load_seasons(years)
    clean = clean_box_scores(raw)
    print(f"      {len(raw)} rows -> {len(clean)} after filtering")

    print("\n[2/7] Player id map")
    athletes = clean[["athlete_id", "athlete_display_name"]].drop_duplicates().values.tolist()
    id_map = build_id_map(athletes)
    counts = clean.groupby("athlete_id").size()
    regulars = counts[counts >= MIN_GAMES_FOR_PREDICTION].index.tolist()
    rate = match_rate(id_map, regulars)
    print(f"      {len(id_map)} athletes; {rate:.1%} of >= {MIN_GAMES_FOR_PREDICTION}-game players matched")
    with open(os.path.join(HERE, "..", "data", "id_map.json"), "w") as fh:
        json.dump(id_map, fh, indent=1, sort_keys=True)

    print("\n[3/7] ESPN schedule + injuries")
    teams = espn_live.load_teams()
    # Look ahead far enough to find a real next game even across an off day,
    # the All-Star break, or (as when this was built) the preseason gap.
    games_raw = espn_live.fetch_upcoming(days=LOOKAHEAD_DAYS)
    injury_report = espn_live.fetch_injury_report()
    injuries = {
        e["name"].lower(): {"status": e["status"], "description": e["description"]}
        for e in (injury_report or {}).get("entries", [])
    }
    today = started.strftime("%Y-%m-%d")
    n_today = sum(1 for g in games_raw if (g.get("start_time") or "")[:10] == today)
    print(f"      {len(games_raw)} games in next {LOOKAHEAD_DAYS}d "
          f"({n_today} today), {len(injuries)} injury entries")
    games = [(g["game_id"], (g.get("start_time") or "")[:10], g["status"], json.dumps(g))
             for g in games_raw]
    injury_rows = [(k, v["status"], v["description"]) for k, v in injuries.items()]

    print("\n[4/7] Team defense ratings")
    defense = compute_team_defense(clean, teams)
    print(f"      {len(defense)} teams ranked")

    print("\n[5/7] Players")
    players = build_players(clean, id_map, teams)
    print(f"      {len(players)} players")

    print("\n[6/7] Predictions")
    model_data = None
    if os.path.exists(MODEL_PATH):
        with open(MODEL_PATH, "rb") as fh:
            model_data = pickle.load(fh)
        print(f"      model trained_at={model_data.get('trained_at')} "
              f"n_players={model_data.get('n_players')}")
    else:
        print("      WARNING: no model found; predictions fall back to averages")

    # Feature histories. Built only when the model actually asks for those
    # columns, so an older pickle keeps working unchanged.
    wanted = set((model_data or {}).get("feature_cols", []))
    opp_hist = absence_hist = opp_latest = None
    if wanted & {"OPP_PTS_ALLOWED", "OPP_PACE", "OPP_PTS_ALLOWED_L10"}:
        opp_hist = opponent_defense_history(clean)
        opp_latest = latest_opponent_ratings(clean)
        print(f"      opponent history: {len(opp_hist)} team-games")
    if "TEAM_MIN_ABSENT" in wanted:
        absence_hist = team_absence_history(clean)
        print(f"      absence history:  {len(absence_hist)} team-games")

    exp_minutes = expected_minutes(clean)
    absent_by_team = absence_from_injuries(players, injuries, exp_minutes)
    print(f"      teams with players out tonight: {len(absent_by_team)}")

    if not args.no_archive:
        archive_injury_report(injury_report, absent_by_team, players, exp_minutes)

    ctx_by_team = next_game_context(games_raw, teams)
    pred_rows, log_rows, skipped = build_predictions(
        clean, id_map, players, model_data, ctx_by_team,
        opp_hist=opp_hist, absence_hist=absence_hist,
        absent_by_team=absent_by_team, opp_latest=opp_latest,
    )
    print(f"      {len(pred_rows)} predictions ({skipped} players under "
          f"{MIN_GAMES_FOR_PREDICTION} games), {len(log_rows)} log rows")

    print("\n[7/7] Validate + write")
    problems = validate(players, pred_rows, rate, clean, SPOT_CHECK_NAMES)
    if problems:
        print("      BUILD REJECTED — existing snapshot left untouched:")
        for p in problems:
            print("        -", p)
        return 1

    meta = {
        "schema_version": SCHEMA_VERSION,
        "built_at": started.isoformat(timespec="seconds"),
        "source_years": ",".join(str(y) for y in years),
        "parquet_max_game_date": str(pd.to_datetime(clean["game_date"]).max().date()),
        "model_trained_at": (model_data or {}).get("trained_at", ""),
        "n_players": len(players),
        "n_predictions": len(pred_rows),
        "id_match_rate": round(rate, 4),
    }

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp"
    write_db(tmp, players=players, pred_rows=pred_rows, log_rows=log_rows,
             games=games, injuries=injury_rows, defense=defense, meta=meta)
    os.replace(tmp, out)

    size_mb = os.path.getsize(out) / 1e6
    print(f"      wrote {out} ({size_mb:.1f} MB) in "
          f"{(datetime.now()-started).total_seconds():.1f}s")
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
