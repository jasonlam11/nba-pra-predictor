"""
Feature engineering shared by training and serving.

This module is deliberately dependency-light -- pandas only. It is imported by
both `scripts/train_model.py` and the snapshot builder, and previously lived
inside `train_model.py`. That meant importing it pulled xgboost and
sklearn.ensemble into the API process at startup, which is wasteful on a
512 MB host. Keeping it standalone guarantees train/serve feature parity
without dragging the training stack along.

The raw game-log shape expected here is nba_api's `playergamelog` output:
columns GAME_DATE, PTS, REB, AST, MIN, MATCHUP, WL. Bulk box-score data is
translated into that shape by `scripts/espn_adapter.py`, so this function never
needs to know where the rows came from.
"""

import pandas as pd


def engineer_features(
    df: pd.DataFrame,
    opp_history: pd.DataFrame = None,
    absence_history: pd.DataFrame = None,
    shot_history: pd.DataFrame = None,
) -> pd.DataFrame:
    """
    Build rolling and contextual features from a raw game-log DataFrame.

    Returns None if there are fewer than 10 rows after processing.

    `opp_history`, `absence_history` and `shot_history`, when given, add
    opponent strength, missing-teammate minutes and shot quality respectively
    (see espn_adapter). All are optional so a model trained without those
    columns keeps working -- make_prediction selects whatever feature list its
    own pickle recorded.
    """
    if df is None or len(df) < 10:
        return None

    # Copy before touching anything: callers reuse the same frame for the
    # response payload, and rewriting GAME_DATE in place used to leave them
    # with datetimes where they expected the original "NOV 05, 2025" strings.
    df = df.copy()

    # Convert before sorting — raw strings like "APR 01, 2024" sort alphabetically wrong
    if not pd.api.types.is_datetime64_any_dtype(df["GAME_DATE"]):
        # nba_api's format, stated explicitly: inferring it per-element is slow
        # and warns, and this runs once per player across the whole league.
        parsed = pd.to_datetime(df["GAME_DATE"], format="%b %d, %Y", errors="coerce")
        if parsed.isna().any():
            parsed = pd.to_datetime(df["GAME_DATE"])  # fall back, don't drop rows
        df["GAME_DATE"] = parsed
    df = df.sort_values("GAME_DATE").reset_index(drop=True)

    # Target
    df["PRA"] = df["PTS"] + df["REB"] + df["AST"]

    # Context features
    df["IS_HOME"] = df["MATCHUP"].apply(lambda x: 1 if "vs." in x else 0)
    df["OPPONENT"] = df["MATCHUP"].apply(lambda x: x.split()[-1])
    df["DAYS_REST"] = df["GAME_DATE"].diff().dt.days.fillna(3).clip(0, 7)

    # Back-to-back indicator — strong fatigue signal
    df["IS_B2B"] = (df["DAYS_REST"] == 1).astype(int)

    # Rolling averages for each stat (shift(1) so we never leak the current game)
    for stat in ["PTS", "REB", "AST", "PRA", "MIN"]:
        df[f"{stat}_L3"]     = df[stat].shift(1).rolling(window=3,  min_periods=1).mean()
        df[f"{stat}_L5"]     = df[stat].shift(1).rolling(window=5,  min_periods=1).mean()
        df[f"{stat}_L10"]    = df[stat].shift(1).rolling(window=10, min_periods=1).mean()
        df[f"{stat}_SEASON"] = df[stat].shift(1).expanding().mean()

    # Consistency: rolling std of PRA over last 5 games (high = streaky, low = reliable)
    df["PRA_STD_L5"] = df["PRA"].shift(1).rolling(window=5, min_periods=2).std().fillna(0)

    # Momentum: wins in last 5 games
    df["WIN"]        = (df["WL"] == "W").astype(int)
    df["WIN_STREAK"] = df["WIN"].shift(1).rolling(window=5, min_periods=1).sum()

    if shot_history is not None and "ESPN_ID" in df.columns:
        before = len(df)
        df = df.merge(shot_history, on=["ESPN_ID", "GAME_DATE"], how="left", validate="m:1")
        if len(df) != before:
            raise ValueError(f"shot join changed row count {before} -> {len(df)}")
        # Players with too little shot history keep a neutral value rather than
        # being dropped -- dropna() below would otherwise delete their rows.
        #
        # The league fallback is load-bearing. A player's own median is NaN when
        # he has no shot rows at all, so filling only within the player leaves
        # NaN, and dropna() then removes him entirely. That silently shrank the
        # training set by 110 players and 6,600 rows and moved the test split,
        # making before/after comparisons meaningless.
        for c in SHOT_FEATURE_COLS:
            if c in df.columns:
                df[c] = df[c].fillna(df[c].median())
                if df[c].isna().any():
                    df[c] = df[c].fillna(float(shot_history[c].median()))

    if absence_history is not None:
        before = len(df)
        # The team tricode is the first token of "DEN vs. MIN".
        df["_team"] = df["MATCHUP"].str.split().str[0]
        df["_gid"] = df["Game_ID"].astype(str)
        ah = absence_history.copy()
        ah["_gid"] = ah["game_id"].astype(str)
        df = df.merge(
            ah[["team_abbreviation", "_gid", "TEAM_MIN_ABSENT"]],
            left_on=["_team", "_gid"], right_on=["team_abbreviation", "_gid"],
            how="left", validate="m:1",
        ).drop(columns=["_team", "_gid", "team_abbreviation"])
        if len(df) != before:
            raise ValueError(
                f"absence join changed row count {before} -> {len(df)}"
            )
        # A team's first games have no squad history yet; 0 means "nobody out",
        # which is also the safe default when the information is unavailable.
        df["TEAM_MIN_ABSENT"] = df["TEAM_MIN_ABSENT"].fillna(0.0)

    if opp_history is not None:
        before = len(df)
        df = df.merge(
            opp_history, on=["OPPONENT", "GAME_DATE"], how="left", validate="m:1"
        )
        if len(df) != before:
            raise ValueError(
                f"opponent join changed row count {before} -> {len(df)}; "
                "opp_history should have one row per (team, date)"
            )

    df = df.dropna()
    return df


# Opponent-strength columns. Kept separate from FEATURE_COLS so a model trained
# without them still loads and predicts: the pickle records its own feature
# list, and make_prediction reads that rather than this module's.
OPP_FEATURE_COLS = [
    "OPP_PTS_ALLOWED", "OPP_REB_ALLOWED", "OPP_AST_ALLOWED",
    "OPP_PTS_ALLOWED_L10", "OPP_PACE",
]

# Expected minutes of rotation teammates who are not playing. Measured as the
# single strongest addition to the base set (see train_model docstring).
ABSENCE_FEATURE_COLS = ["TEAM_MIN_ABSENT"]

# Shot-location quality. The box score records whether shots went in; this
# records how good they were, which is the more stable of the two and is what
# recent scoring regresses toward.
SHOT_FEATURE_COLS = [
    "SHOT_EXP_PTS_L5", "SHOT_EXP_PTS_L10",
    "SHOT_FGA_L5", "SHOT_DIST_L5", "SHOT_HOT_L5",
]


FEATURE_COLS = [
    "IS_HOME", "DAYS_REST", "IS_B2B",
    "PTS_L3", "PTS_L5", "PTS_L10", "PTS_SEASON",
    "REB_L3", "REB_L5", "REB_L10", "REB_SEASON",
    "AST_L3", "AST_L5", "AST_L10", "AST_SEASON",
    "PRA_L3", "PRA_L5", "PRA_L10", "PRA_SEASON",
    "MIN_L3", "MIN_L5", "MIN_L10", "MIN_SEASON",
    "PRA_STD_L5", "WIN_STREAK",
]
