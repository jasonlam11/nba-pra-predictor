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


def opponent_defense_history(df: pd.DataFrame) -> pd.DataFrame:
    """
    Per-team, per-game defensive ratings using ONLY games played before that game.

    Returns columns: OPPONENT, GAME_DATE, OPP_PTS_ALLOWED, OPP_REB_ALLOWED,
    OPP_AST_ALLOWED -- one row per (team, game date), where the values describe
    what that team had allowed *going into* that game.

    Leakage is the whole difficulty here. A season-long "team X allows 112 PPG"
    includes the game being predicted, so a model fed that number is partly
    reading the answer. Everything below is an expanding mean shifted by one
    game, so a row never sees its own result.

    `df` is cleaned box scores (see clean_box_scores) covering whole games --
    pass the league-wide frame, not one player's rows.
    """
    d = df.copy()
    d["_date"] = pd.to_datetime(d["game_date"])

    # A player's row records their own team's output against `opponent`, so
    # summing a game's rows by opponent gives what that opponent conceded.
    game_totals = d.groupby("game_id")["points"].sum().rename("total_points")
    d = d.merge(game_totals, on="game_id", how="left")

    conceded = (
        d.groupby(["opponent_team_abbreviation", "game_id", "_date"])
        .agg(points=("points", "sum"), rebounds=("rebounds", "sum"),
             assists=("assists", "sum"), total_points=("total_points", "first"))
        .reset_index()
        .rename(columns={"opponent_team_abbreviation": "OPPONENT"})
        .sort_values(["OPPONENT", "_date"])
    )

    g = conceded.groupby("OPPONENT")
    for src, dst in (("points", "OPP_PTS_ALLOWED"),
                     ("rebounds", "OPP_REB_ALLOWED"),
                     ("assists", "OPP_AST_ALLOWED")):
        conceded[dst] = g[src].transform(lambda s: s.shift(1).expanding().mean())

    # Season-to-date is slow to react to a defense that has changed (a trade, a
    # returning rim protector), so also carry a 10-game form window.
    conceded["OPP_PTS_ALLOWED_L10"] = g["points"].transform(
        lambda s: s.shift(1).rolling(10, min_periods=1).mean()
    )
    # Pace proxy: total points scored by BOTH teams in the opponent's games.
    # Points-allowed alone conflates a fast team with a bad defense.
    conceded["OPP_PACE"] = g["total_points"].transform(
        lambda s: s.shift(1).rolling(10, min_periods=1).mean()
    )

    # A team's first game of the earliest season has no prior games. Fill from
    # the league's expanding average as of the same date -- also computed from
    # earlier games only, so this does not reintroduce leakage.
    league = conceded.sort_values("_date")
    for col in ("OPP_PTS_ALLOWED", "OPP_REB_ALLOWED", "OPP_AST_ALLOWED",
                "OPP_PTS_ALLOWED_L10", "OPP_PACE"):
        league_avg = league[col].expanding().mean()
        conceded.loc[league.index, col] = league.loc[:, col].fillna(league_avg)
        # Anything still missing (the very first rows) falls back to the
        # column's overall mean, which affects a handful of games.
        conceded[col] = conceded[col].fillna(conceded[col].mean())

    out = conceded[["OPPONENT", "_date", "OPP_PTS_ALLOWED",
                    "OPP_REB_ALLOWED", "OPP_AST_ALLOWED",
                    "OPP_PTS_ALLOWED_L10", "OPP_PACE"]].copy()
    out = out.rename(columns={"_date": "GAME_DATE"})
    return out.sort_values("GAME_DATE").reset_index(drop=True)


SQUAD_LOOKBACK_GAMES = 5


def team_absence_history(df: pd.DataFrame) -> pd.DataFrame:
    """
    Per-team, per-game: how many expected minutes of the usual squad are missing.

    This is the strongest signal available from box scores alone. When a
    rotation player sits, his minutes and usage are redistributed, and his
    teammates' PRA rises accordingly -- measured across four seasons, players in
    the top quintile of absent-teammate minutes beat their own 10-game form by
    +2.2 PRA while the bottom quintile fell 1.5 short, a 3.7 PRA spread.

    Returns columns: team_abbreviation, game_id, TEAM_MIN_ABSENT.

    Definitions, all using prior games only:
      - a player's expected minutes = his 10-game average BEFORE this game
      - the "usual squad" = anyone who appeared in the team's previous
        SQUAD_LOOKBACK_GAMES games
      - absent = in the usual squad, but no box-score row for this game

    NOTE on train/serve skew: here absence is who *did not play*, which is only
    knowable after tip-off. At prediction time the daily job substitutes the
    injury report, which is a noisier proxy -- so the production benefit is
    smaller than the offline measurement. See build_snapshot.absence_from_injuries.
    """
    d = df[["game_id", "game_date", "athlete_id", "team_abbreviation", "minutes"]].copy()
    d["game_date"] = pd.to_datetime(d["game_date"])
    d["minutes"] = pd.to_numeric(d["minutes"], errors="coerce").fillna(0.0)
    d = d.sort_values(["athlete_id", "game_date"])

    # Expected minutes going into each game (shift(1) => never sees tonight).
    d["MIN_L10_PRE"] = d.groupby("athlete_id")["minutes"].transform(
        lambda s: s.shift(1).rolling(10, min_periods=3).mean()
    )

    out = []
    for team, tdf in d.groupby("team_abbreviation", sort=False):
        order = (
            tdf[["game_id", "game_date"]]
            .drop_duplicates()
            .sort_values("game_date")
            .reset_index(drop=True)
        )
        if len(order) <= SQUAD_LOOKBACK_GAMES:
            continue
        idx = {g: i for i, g in enumerate(order["game_id"])}
        t = tdf.assign(_i=tdf["game_id"].map(idx)).dropna(subset=["_i"])

        played = (
            t.pivot_table(index="_i", columns="athlete_id", values="minutes",
                          aggfunc="size", fill_value=0)
            .reindex(range(len(order)), fill_value=0)
            .gt(0)
        )
        # Last known expected minutes for every player at every team-game,
        # carried forward across games they missed.
        expected = (
            t.pivot_table(index="_i", columns="athlete_id", values="MIN_L10_PRE",
                          aggfunc="last")
            .reindex(range(len(order)))
            .ffill()
            .fillna(0.0)
        )
        # Appeared in any of the previous N games.
        squad = (
            played.rolling(SQUAD_LOOKBACK_GAMES, min_periods=1).sum().shift(1).fillna(0).gt(0)
        )

        absent = squad & ~played
        totals = (expected.where(absent, 0.0)).sum(axis=1)

        out.append(pd.DataFrame({
            "team_abbreviation": team,
            "game_id": order["game_id"].values,
            "TEAM_MIN_ABSENT": totals.values,
        }).iloc[SQUAD_LOOKBACK_GAMES:])

    if not out:
        return pd.DataFrame(columns=["team_abbreviation", "game_id", "TEAM_MIN_ABSENT"])
    return pd.concat(out, ignore_index=True)


def latest_opponent_ratings(df: pd.DataFrame) -> dict:
    """
    {tricode: {OPP_* : value}} as they stand going into the NEXT game.

    opponent_defense_history gives each past game its own pre-game rating; this
    is the same calculation carried one game further, using every game played
    so far, which is what a prediction for tonight needs.
    """
    d = df.copy()
    d["_date"] = pd.to_datetime(d["game_date"])
    game_totals = d.groupby("game_id")["points"].sum().rename("total_points")
    d = d.merge(game_totals, on="game_id", how="left")

    conceded = (
        d.groupby(["opponent_team_abbreviation", "game_id", "_date"])
        .agg(points=("points", "sum"), rebounds=("rebounds", "sum"),
             assists=("assists", "sum"), total_points=("total_points", "first"))
        .reset_index()
        .rename(columns={"opponent_team_abbreviation": "OPPONENT"})
        .sort_values(["OPPONENT", "_date"])
    )

    out = {}
    for team, t in conceded.groupby("OPPONENT"):
        out[str(team)] = {
            "OPP_PTS_ALLOWED": float(t["points"].mean()),
            "OPP_REB_ALLOWED": float(t["rebounds"].mean()),
            "OPP_AST_ALLOWED": float(t["assists"].mean()),
            "OPP_PTS_ALLOWED_L10": float(t["points"].tail(10).mean()),
            "OPP_PACE": float(t["total_points"].tail(10).mean()),
        }
    return out
