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
    # Stable join key. PLAYER_ID is whatever the caller passed -- the ESPN id
    # during training, the nba_api id when building the snapshot -- so anything
    # joining per-player data needs an identifier that does not change meaning.
    out["ESPN_ID"] = d["athlete_id"].astype("int64").values

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


# Distance buckets for the league shooting curve, in feet.
SHOT_DISTANCE_BINS = [-1, 4, 9, 15, 21, 25, 30, 100]


def _game_date_map(shots: pd.DataFrame, clean: pd.DataFrame) -> dict:
    """
    {nba game_id: game_date}, derived without any extra data source.

    This exists because of a trap. NBA game ids are NOT chronological -- game
    0022500009 is Christmas Day -- so they cannot be ordered into dates. The
    obvious fix, sportsdataverse's nba_stats_player_game_logs, carries dates but
    is refreshed far less often than the shot files; relying on it would quietly
    drop the most recent games in-season, which are exactly the ones a rolling
    feature needs.

    So games are matched between the two datasets on something both already
    contain: the pair of teams and each one's field-goal points (ESPN's points
    minus free throws). That key is unique, and it depends only on sources the
    daily job already refreshes. Measured on 2025-26: 99.4% of games matched,
    and 100.00% of those dates agree with the NBA's official record.
    """
    s = shots.copy()
    s["tri"] = s["team_tricode"].replace(ESPN_TO_NBA_TRICODE)
    s["fgp"] = (s["shot_result"] == "Made").astype(int) * s["shot_value"]
    nba = s.groupby(["game_id", "tri"])["fgp"].sum().reset_index()
    nba_key = (
        nba.sort_values(["game_id", "tri"]).groupby("game_id")
        .apply(lambda d: "|".join(f"{t}:{int(p)}" for t, p in zip(d.tri, d.fgp)),
               include_groups=False)
        .rename("key").reset_index()
    )

    e = clean.assign(fgp=clean["points"] - clean["free_throws_made"])
    esp = e.groupby(["game_id", "game_date", "team_abbreviation"])["fgp"].sum().reset_index()
    esp_key = (
        esp.sort_values(["game_id", "team_abbreviation"]).groupby(["game_id", "game_date"])
        .apply(lambda d: "|".join(f"{t}:{int(p)}" for t, p in zip(d.team_abbreviation, d.fgp)),
               include_groups=False)
        .rename("key").reset_index()
    )

    # A key shared by two games means we cannot tell which date is which, so
    # drop it rather than guess. Affects ~0.1% of games.
    nba_key = nba_key[~nba_key["key"].duplicated(keep=False)]
    esp_key = esp_key[~esp_key["key"].duplicated(keep=False)]

    m = nba_key.merge(esp_key, on="key", how="inner", suffixes=("_nba", "_espn"))
    return dict(zip(m["game_id_nba"], pd.to_datetime(m["game_date"])))


def shot_quality_history(shots: pd.DataFrame, clean: pd.DataFrame,
                         nba_to_espn: dict) -> pd.DataFrame:
    """
    Rolling shot-quality features per (ESPN athlete id, game date).

    The idea this captures is one the box score cannot express. PTS_L5 -- the
    model's single most important input -- conflates two different things: how
    many and how good a player's shot attempts are, which is stable, and whether
    those attempts went in, which is noisy. Scoring a player's shots by where
    they were taken separates the two.

    Measured directly: expected points from shot locations predicts a player's
    next game better than their actual recent points (MAE 4.32 vs 4.43), and
    players shooting far above their shot quality regress by ~2 points next game
    while those below bounce back ~1.9 -- a swing the model was blind to.

    Columns: SHOT_EXP_PTS_L5/L10 (shot quality), SHOT_FGA_L5 (volume),
    SHOT_DIST_L5 (shot profile), SHOT_HOT_L5 (recent over-performance, which
    tends to reverse).

    Every value is shifted one game, so a row never sees its own result.
    """
    # 2 regular season, 4 playoffs, 5 play-in, 6 NBA Cup final. All are real
    # basketball and all appear in the box scores we join against; excluding any
    # of them leaves those games with no shot history, which the median fill
    # then silently papers over.
    s = shots[shots["season_type_id"].astype(str).isin({"2", "4", "5", "6"})].copy()
    s["made"] = (s["shot_result"] == "Made").astype(int)
    s["act"] = s["made"] * s["shot_value"]
    s["bucket"] = pd.cut(s["shot_distance"], SHOT_DISTANCE_BINS)

    # League curve fitted on the EARLIEST season present, then held fixed, so no
    # game is ever scored using a curve derived from its own season.
    first_season = s["season"].min()
    curve = (
        s[s["season"] == first_season]
        .groupby("bucket", observed=True)
        .apply(lambda d: float((d["made"] * d["shot_value"]).mean()), include_groups=False)
    )
    s["exp"] = s["bucket"].map(curve).astype(float)

    dates = _game_date_map(s, clean)
    pg = (
        s.groupby(["person_id", "game_id"])
        .agg(fga=("made", "size"), act=("act", "sum"),
             exp=("exp", "sum"), dist=("shot_distance", "mean"))
        .reset_index()
    )
    pg["GAME_DATE"] = pg["game_id"].map(dates)
    pg = pg.dropna(subset=["GAME_DATE"]).sort_values(["person_id", "GAME_DATE"])

    g = pg.groupby("person_id")
    pg["SHOT_EXP_PTS_L5"] = g["exp"].transform(lambda x: x.shift(1).rolling(5, min_periods=3).mean())
    pg["SHOT_EXP_PTS_L10"] = g["exp"].transform(lambda x: x.shift(1).rolling(10, min_periods=3).mean())
    pg["SHOT_FGA_L5"] = g["fga"].transform(lambda x: x.shift(1).rolling(5, min_periods=3).mean())
    pg["SHOT_DIST_L5"] = g["dist"].transform(lambda x: x.shift(1).rolling(5, min_periods=3).mean())
    pg["SHOT_HOT_L5"] = (
        g["act"].transform(lambda x: x.shift(1).rolling(5, min_periods=3).mean())
        - pg["SHOT_EXP_PTS_L5"]
    )

    # Shots are keyed by nba_api player id; everything downstream joins on the
    # ESPN athlete id, which is the only id present in the box-score rows.
    pg["ESPN_ID"] = pg["person_id"].map(nba_to_espn)
    cols = ["SHOT_EXP_PTS_L5", "SHOT_EXP_PTS_L10", "SHOT_FGA_L5", "SHOT_DIST_L5", "SHOT_HOT_L5"]
    out = pg.dropna(subset=["ESPN_ID"] + cols).copy()
    out["ESPN_ID"] = out["ESPN_ID"].astype("int64")
    out = out.drop_duplicates(subset=["ESPN_ID", "GAME_DATE"], keep="last")
    return out[["ESPN_ID", "GAME_DATE"] + cols].reset_index(drop=True)
