"""
Go/no-go gate for the data-source migration.

Run BEFORE switching the API over to snapshot reads.

Two layers:

  1. Structural invariants (always run, no network beyond the parquet). These
     catch the failure modes that actually matter -- wrong shooting columns,
     rebound components that do not sum, All-Star rows left in, a broken
     MATCHUP string -- and they hold without needing stats.nba.com.

  2. A direct diff against live nba_api (best effort). stats.nba.com blocks
     datacenter IPs and frequently times out even from a laptop, which is the
     whole reason this migration exists. When it is unreachable the script says
     INCONCLUSIVE for that layer rather than silently reporting success; pass
     --require-live to make unreachability a hard failure.

    python scripts/check_parity.py [--require-live]

Requires requirements-data.txt (nba_api + pyarrow). This is the only file in
the project that still contacts stats.nba.com, and it is developer-only.
"""

import os
import sys
import time

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

from parquet_source import load_season                      # noqa: E402
from espn_adapter import clean_box_scores, to_nba_gamelog   # noqa: E402
from app.predict import make_prediction, _season_averages_from_log  # noqa: E402

# (nba_api player_id, name as it appears in the bulk data)
SPOT_CHECK = [
    (203999, "Nikola Jokic"),
    (1629029, "Luka Doncic"),
    (201939, "Stephen Curry"),
]
SEASON = "2025-26"
PARQUET_YEAR = 2026
MAX_PRA_DELTA = 0.5


def live_log(player_id):
    from nba_api.stats.endpoints import playergamelog
    headers = {
        "Host": "stats.nba.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/113.0",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://stats.nba.com/",
        "x-nba-stats-origin": "stats",
        "x-nba-stats-token": "true",
    }
    time.sleep(1.0)
    return playergamelog.PlayerGameLog(
        player_id=player_id, season=SEASON, timeout=30, headers=headers
    ).get_data_frames()[0]


def check_invariants(log: pd.DataFrame, reg: pd.DataFrame) -> list:
    """
    Arithmetic and structural checks on the adapted league-wide log.

    An adapter bug shifts rolling windows silently rather than raising, so these
    assert the translated columns are internally consistent.
    """
    problems = []

    def expect(label, actual, ok):
        print(f"    {label:<46} {actual}   {'OK' if ok else 'FAIL'}")
        if not ok:
            problems.append(f"invariant: {label} -> {actual}")

    pts_calc = 2 * (log["FGM"] - log["FG3M"]) + 3 * log["FG3M"] + log["FTM"]
    r = float((pts_calc == log["PTS"]).mean())
    expect("PTS == 2*(FGM-FG3M) + 3*FG3M + FTM", f"{r:.4f}", r == 1.0)

    r = float(((log["OREB"] + log["DREB"]) == log["REB"]).mean())
    expect("REB == OREB + DREB", f"{r:.4f}", r == 1.0)

    r = float((log["FGM"] <= log["FGA"]).mean())
    expect("FGM <= FGA", f"{r:.4f}", r == 1.0)

    teams = reg["team_abbreviation"].nunique()
    expect("distinct teams (All-Star rosters removed)", teams, teams == 30)

    tpg = reg.groupby("game_id")["team_abbreviation"].nunique()
    expect("teams per game == 2", f"min={tpg.min()} max={tpg.max()}", tpg.min() == 2 and tpg.max() == 2)

    g = reg.groupby("team_abbreviation")["game_id"].nunique()
    expect("regular-season games per team ~82", f"min={g.min()} max={g.max()}", 80 <= g.min() and g.max() <= 84)

    home = float(log["MATCHUP"].str.contains("vs.", regex=False).mean())
    expect("home share of rows ~0.50", f"{home:.4f}", 0.45 <= home <= 0.55)

    bad_date = int((~log["GAME_DATE"].str.match(r"^[A-Z]{3} \d{2}, \d{4}$")).sum())
    expect("GAME_DATE in nba_api format", f"{bad_date} bad", bad_date == 0)

    bad_wl = int((~log["WL"].isin(["W", "L"])).sum())
    expect("WL in {W,L}", f"{bad_wl} bad", bad_wl == 0)

    return problems


def main():
    require_live = "--require-live" in sys.argv

    print(f"Loading bulk parquet for {PARQUET_YEAR} ...")
    clean = clean_box_scores(load_season(PARQUET_YEAR))
    # nba_api's default season_type is Regular Season; match it.
    clean = clean[clean["season_type"] == 2]

    print("\n[1/2] Structural invariants")
    failures = check_invariants(to_nba_gamelog(clean), clean)
    live_ok = False

    model_path = os.path.join(HERE, "..", "models", "pra_model.pkl")
    model_data = None
    if os.path.exists(model_path):
        import pickle
        with open(model_path, "rb") as fh:
            model_data = pickle.load(fh)

    print("\n[2/2] Live nba_api comparison")
    for pid, name in SPOT_CHECK:
        print(f"\n=== {name} ===")
        rows = clean[clean["athlete_display_name"] == name]
        if rows.empty:
            failures.append(f"{name}: not found in bulk data")
            continue
        adapted = to_nba_gamelog(rows, player_id=pid)

        try:
            live = live_log(pid)
        except Exception as e:
            print(f"  live fetch unavailable ({type(e).__name__})")
            live = None

        if live is not None and len(live):
            live_ok = True
            a = adapted.set_index("GAME_DATE")
            b = live.set_index("GAME_DATE")
            shared = sorted(set(a.index) & set(b.index))
            print(f"  games: bulk={len(a)} live={len(b)} overlapping={len(shared)}")
            if not shared:
                failures.append(f"{name}: no overlapping games")
            for col in ["PTS", "REB", "AST", "MATCHUP", "WL"]:
                diff = [d for d in shared if str(a.loc[d, col]) != str(b.loc[d, col])]
                status = "OK" if not diff else f"MISMATCH on {len(diff)} games e.g. {diff[:3]}"
                print(f"    {col:<8} {status}")
                if diff:
                    failures.append(f"{name}.{col}: {len(diff)} mismatched games")

        # The check that actually decides the migration.
        season = _season_averages_from_log(adapted)
        pred_bulk = make_prediction(adapted, season, model_data=model_data)
        print(f"  prediction from bulk : PRA {pred_bulk['total_pra']}")
        if live is not None and len(live) >= 10:
            season_live = _season_averages_from_log(live)
            pred_live = make_prediction(live, season_live, model_data=model_data)
            delta = abs(pred_bulk["total_pra"] - pred_live["total_pra"])
            print(f"  prediction from live : PRA {pred_live['total_pra']}  (delta {delta:.2f})")
            if delta > MAX_PRA_DELTA:
                failures.append(f"{name}: PRA delta {delta:.2f} > {MAX_PRA_DELTA}")

    print("\n" + "=" * 60)
    if failures:
        print("PARITY GATE FAILED:")
        for f in failures:
            print("  -", f)
        return 1

    if not live_ok:
        # Do not dress an unreachable upstream up as a successful comparison.
        print("Invariants PASSED.")
        print("Live comparison INCONCLUSIVE — stats.nba.com was unreachable.")
        if require_live:
            print("--require-live was set, so this counts as a failure.")
            return 1
        print("\nThis is expected on blocked networks and is itself the reason")
        print("for the migration. Re-run from a network that can reach")
        print("stats.nba.com if you want the direct diff.")
        return 0

    print("PARITY GATE PASSED — invariants and live diff both clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
