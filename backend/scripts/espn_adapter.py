"""
Translates sportsdataverse/ESPN bulk box scores into nba_api `playergamelog` shape.

The whole point is that `app/features.py:engineer_features` is NOT modified.
It keeps consuming GAME_DATE / PTS / REB / AST / MIN / MATCHUP / WL exactly as
it always did, so the features the model trains on and the features it serves
on stay identical by construction rather than by inspection.

Three filtering details matter for parity, and getting any of them wrong
silently corrupts every rolling window rather than raising:

  1. All-Star rosters appear as the fake teams STARS / STRIPES / WORLD. A
     30-tricode whitelist removes them. This is deliberately not a season_type
     blacklist -- season_type 5 is the play-in, which is real basketball.
  2. did_not_play rows exist here (~6k per season) but `playergamelog` never
     returns them. Leaving them in would shift L5/L10 windows by inserting
     zero-minute games. The `active` column is NOT a safe substitute: rows
     exist with active=False and 23 minutes played.
  3. ESPN tricodes differ from NBA's for six teams, and MATCHUP strings are
     parsed downstream for the opponent, so they must be translated.
"""

import numpy as np
import pandas as pd

# ESPN abbreviation -> NBA abbreviation. The other 24 teams match exactly.
ESPN_TO_NBA_TRICODE = {
    "GS": "GSW",
    "NO": "NOP",
    "NY": "NYK",
    "SA": "SAS",
    "UTAH": "UTA",
    "WSH": "WAS",
}

NBA_TRICODES = {
    "ATL", "BKN", "BOS", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}


def _tricode(series: pd.Series) -> pd.Series:
    return series.astype("string").replace(ESPN_TO_NBA_TRICODE)


def _pct(made: pd.Series, attempted: pd.Series) -> pd.Series:
    """Shooting percentage, with 0 attempts -> 0.0 to match nba_api."""
    made = pd.to_numeric(made, errors="coerce").fillna(0)
    attempted = pd.to_numeric(attempted, errors="coerce").fillna(0)
    return (made / attempted.replace(0, np.nan)).fillna(0.0).round(3)


def clean_box_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the three parity filters. Run once over the whole frame."""
    df = df.copy()

    df["team_abbreviation"] = _tricode(df["team_abbreviation"])
    df["opponent_team_abbreviation"] = _tricode(df["opponent_team_abbreviation"])

    # 1 — drop All-Star exhibition rosters
    df = df[df["team_abbreviation"].isin(NBA_TRICODES)]
    df = df[df["opponent_team_abbreviation"].isin(NBA_TRICODES)]

    # 2 — drop games the player did not appear in
    if "did_not_play" in df.columns:
        df = df[df["did_not_play"] != True]  # noqa: E712 (pandas mask, not identity)
    df = df[pd.to_numeric(df["minutes"], errors="coerce").notna()]

    # 3 — one row per player per game
    df = df.drop_duplicates(subset=["game_id", "athlete_id"])

    # athlete_id arrives as float64 (4066648.0). Left alone it silently breaks
    # every dict lookup keyed by the id, so normalize once, here.
    df = df[df["athlete_id"].notna()]
    df["athlete_id"] = df["athlete_id"].astype("int64")

    return df.reset_index(drop=True)


def to_nba_gamelog(df: pd.DataFrame, player_id: int = None) -> pd.DataFrame:
    """
    Convert cleaned box-score rows for ONE player into playergamelog shape.

    Returns rows sorted newest-first, which is nba_api's convention and what
    `_recent_stats_from_log`/`_compute_reasons` rely on via `.head(n)`.
    `engineer_features` re-sorts ascending internally, so both are satisfied.
    """
    if df is None or len(df) == 0:
        return pd.DataFrame()

    d = df.copy()
    dates = pd.to_datetime(d["game_date"])

    is_home = d["home_away"].astype("string").str.lower().eq("home")
    sep = np.where(is_home, " vs. ", " @ ")

    out = pd.DataFrame({
        # nba_api emits "NOV 05, 2025"; the frontend renders this string
        # directly, so reproducing the format keeps LastFiveChart unchanged.
        "GAME_DATE": dates.dt.strftime("%b %d, %Y").str.upper(),
        "MATCHUP": d["team_abbreviation"].astype(str) + sep + d["opponent_team_abbreviation"].astype(str),
        "WL": np.where(d["team_winner"] == True, "W", "L"),  # noqa: E712
        "MIN": pd.to_numeric(d["minutes"], errors="coerce").fillna(0).astype(float),
        "PTS": pd.to_numeric(d["points"], errors="coerce").fillna(0).astype(int),
        "REB": pd.to_numeric(d["rebounds"], errors="coerce").fillna(0).astype(int),
        "AST": pd.to_numeric(d["assists"], errors="coerce").fillna(0).astype(int),
        "FGM": pd.to_numeric(d["field_goals_made"], errors="coerce").fillna(0).astype(int),
        "FGA": pd.to_numeric(d["field_goals_attempted"], errors="coerce").fillna(0).astype(int),
        "FG3M": pd.to_numeric(d["three_point_field_goals_made"], errors="coerce").fillna(0).astype(int),
        "FG3A": pd.to_numeric(d["three_point_field_goals_attempted"], errors="coerce").fillna(0).astype(int),
        "FTM": pd.to_numeric(d["free_throws_made"], errors="coerce").fillna(0).astype(int),
        "FTA": pd.to_numeric(d["free_throws_attempted"], errors="coerce").fillna(0).astype(int),
        "OREB": pd.to_numeric(d["offensive_rebounds"], errors="coerce").fillna(0).astype(int),
        "DREB": pd.to_numeric(d["defensive_rebounds"], errors="coerce").fillna(0).astype(int),
        "STL": pd.to_numeric(d["steals"], errors="coerce").fillna(0).astype(int),
        "BLK": pd.to_numeric(d["blocks"], errors="coerce").fillna(0).astype(int),
        "TOV": pd.to_numeric(d["turnovers"], errors="coerce").fillna(0).astype(int),
        "PF": pd.to_numeric(d["fouls"], errors="coerce").fillna(0).astype(int),
        "PLUS_MINUS": pd.to_numeric(d["plus_minus"], errors="coerce").fillna(0).astype(float),
        "Game_ID": d["game_id"].astype(str),
        "_SORT_DATE": dates,
    })
    out["FG_PCT"] = _pct(d["field_goals_made"], d["field_goals_attempted"]).values
    out["FG3_PCT"] = _pct(d["three_point_field_goals_made"], d["three_point_field_goals_attempted"]).values
    out["FT_PCT"] = _pct(d["free_throws_made"], d["free_throws_attempted"]).values
    out["PLAYER_ID"] = player_id if player_id is not None else d["athlete_id"].values

    out = out.sort_values("_SORT_DATE", ascending=False).drop(columns=["_SORT_DATE"])
    return out.reset_index(drop=True)
