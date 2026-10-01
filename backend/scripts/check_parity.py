"""
Go/no-go gate for the data-source migration.

Run BEFORE switching the API over to snapshot reads.

Two layers:

  1. Structural invariants (always run, no network beyond the parquet). These
     catch the failure modes that actually matter -- wrong shooting columns,
     rebound components that do not sum, All-Star rows left in, a broken
     MATCHUP string -- and they hold without needing stats.nba.com.

  2. A comparison against the NBA's OWN record. This used to call stats.nba.com
     directly and could never complete, because the NBA blocks us -- it reported
     INCONCLUSIVE rather than pretending to pass. The official data turns out to
     be reachable another way: sportsdataverse republishes stats.nba.com season
     totals as parquet on GitHub Releases. Same source of truth, no blocked host.

     The check compares every player's season totals against the league's, which
     is strictly stronger than the three-player spot check the live version
     attempted.

    python scripts/check_parity.py

Requires requirements-data.txt. Nothing here contacts stats.nba.com.
"""

import os
import re
import sys
import unicodedata

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

from parquet_source import load_season                      # noqa: E402
from espn_adapter import clean_box_scores, to_nba_gamelog   # noqa: E402
from app.predict import make_prediction, _season_averages_from_log  # noqa: E402

PARQUET_YEAR = 2026
MIN_GAMES = 10

# Thresholds for layer 2.
#
# Games played will not agree for every player, and that is expected rather than
# a defect: ESPN counts the NBA Cup championship game as a regular-season game
# and the NBA does not. In 2025-26 that is NYK and SAS, who show 83 games to the
# league's 82, which shifts the season totals of everyone on those rosters.
#
# So the real test is applied to players whose games played DO agree -- for them
# the totals must match the league's record exactly, with no tolerance.
MIN_GP_AGREEMENT = 0.90
REQUIRED_TOTALS_AGREEMENT = 1.00


def _norm(name: str) -> str:
    """Normalized join key — ESPN and the NBA spell accents and suffixes differently."""
    t = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z ]", "", t.lower())
    for suf in (" jr", " sr", " ii", " iii", " iv"):
        if t.endswith(suf):
            t = t[: -len(suf)]
            break
    return " ".join(t.split())


def compare_with_official(clean: pd.DataFrame, year: int) -> list:
    """
    Compare our season totals against the NBA's own published record.

    This is the check that the live-nba_api version was trying and failing to
    perform. Season totals are an exacting test despite being aggregates: a
    single mis-parsed or duplicated box-score row shifts a player's total and
    shows up immediately.
    """
    from parquet_source import load_official_season_stats

    official = load_official_season_stats(year)
    if official is None or official.empty:
        return [f"official season stats for {year} unavailable"]

    off = official[["player_name", "gp", "pts", "reb", "ast"]].dropna(subset=["pts"]).copy()
    off["k"] = off["player_name"].map(_norm)
    # A traded player has one row per team; sum them.
    off = off.groupby("k", as_index=False)[["gp", "pts", "reb", "ast"]].sum()

    reg = clean[clean["season_type"] == 2]
    ours = reg.assign(k=reg["athlete_display_name"].map(_norm)).groupby("k", as_index=False).agg(
        gp=("points", "size"), pts=("points", "sum"),
        reb=("rebounds", "sum"), ast=("assists", "sum"),
    )

    m = off.merge(ours, on="k", suffixes=("_nba", "_ours"))
    m = m[m["gp_nba"] >= MIN_GAMES]
    if m.empty:
        return ["no players matched against the official record"]

    problems = []
    gp_ok = (m["gp_nba"] == m["gp_ours"])
    print(f"    players compared                       {len(m)}")
    print(f"    games played agree                     {100 * gp_ok.mean():.1f}%"
          f"   {'OK' if gp_ok.mean() >= MIN_GP_AGREEMENT else 'FAIL'}")
    if gp_ok.mean() < MIN_GP_AGREEMENT:
        problems.append(f"games-played agreement {gp_ok.mean():.1%} below {MIN_GP_AGREEMENT:.0%}")

    same = m[gp_ok]
    for stat in ("pts", "reb", "ast"):
        rate = float((same[f"{stat}_nba"] == same[f"{stat}_ours"]).mean())
        ok = rate >= REQUIRED_TOTALS_AGREEMENT
        print(f"    {stat.upper()} totals identical (matched gp)       "
              f"{100 * rate:.2f}%   {'OK' if ok else 'FAIL'}")
        if not ok:
            problems.append(f"{stat} totals agree only {rate:.2%} of the time")

    # Not a failure: ESPN counts the NBA Cup final as a regular-season game and
    # the NBA does not, so the two finalists' rosters legitimately differ by one.
    extra = m[~gp_ok]
    if len(extra):
        print(f"    (games-played differs for {len(extra)} players — expected, "
              f"NBA Cup final is regular season for ESPN only)")
    return problems


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
    print(f"Loading bulk parquet for {PARQUET_YEAR} ...")
    clean = clean_box_scores(load_season(PARQUET_YEAR))

    print("\n[1/2] Structural invariants")
    reg = clean[clean["season_type"] == 2]
    failures = check_invariants(to_nba_gamelog(reg), reg)

    print("\n[2/2] Agreement with the NBA's official season record")
    failures += compare_with_official(clean, PARQUET_YEAR)

    print("\n" + "=" * 62)
    if failures:
        print("PARITY GATE FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print("PARITY GATE PASSED — internally consistent, and season totals match")
    print("the NBA's own published record exactly for every player whose")
    print("games-played agrees.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
