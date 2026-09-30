"""
Prediction and stat-summary helpers shared by the API and the snapshot builder.

These used to live in `app/main.py`. The daily builder now precomputes the exact
`/players/{id}/stats` payload the API used to compute on demand, so both sides
must run identical code -- importing from one place is what makes that true
rather than aspirational.

`make_prediction` takes `model_data` explicitly instead of reading a module
global, so the builder can load a candidate model without monkeypatching the
API's.
"""

import pandas as pd

from app.features import engineer_features, FEATURE_COLS


def _season_averages_from_log(df: pd.DataFrame) -> dict:
    """Compute season averages directly from a game-log DataFrame."""
    return {
        "points":      round(float(df["PTS"].mean()), 1),
        "rebounds":    round(float(df["REB"].mean()), 1),
        "assists":     round(float(df["AST"].mean()), 1),
        "minutes":     round(float(df["MIN"].mean()), 1) if "MIN" in df.columns else 0.0,
        "games_played": len(df),
        "fg_pct":      round(float(df["FG_PCT"].mean()), 3) if "FG_PCT" in df.columns else 0.0,
        "fg3_pct":     round(float(df["FG3_PCT"].mean()), 3) if "FG3_PCT" in df.columns else 0.0,
        "ft_pct":      round(float(df["FT_PCT"].mean()), 3) if "FT_PCT" in df.columns else 0.0,
    }


def _recent_stats_from_log(df: pd.DataFrame, num_games: int = 5):
    """Return (games_list, averages) for the most recent N games."""
    recent = df.head(num_games)

    games_list = []
    for _, game in recent.iterrows():
        games_list.append({
            "date":     game["GAME_DATE"],
            "opponent": game["MATCHUP"].split()[-1],
            "home":     "vs." in game["MATCHUP"],
            "points":   int(game["PTS"]),
            "rebounds": int(game["REB"]),
            "assists":  int(game["AST"]),
            "minutes":  int(float(game["MIN"])) if pd.notna(game.get("MIN")) else 0,
            "result":   game["WL"],
        })

    averages = {
        "points":      round(float(recent["PTS"].mean()), 1),
        "rebounds":    round(float(recent["REB"].mean()), 1),
        "assists":     round(float(recent["AST"].mean()), 1),
        "minutes":     round(float(recent["MIN"].mean()), 1) if "MIN" in recent.columns else 0.0,
        "games_played": len(recent),
    }
    return games_list, averages


def _compute_reasons(df: pd.DataFrame) -> dict:
    """
    Return 5 bullet-point reasons per stat type (pra/pts/reb/ast).
    Each reason is a plain string explaining recent performance context.
    """
    # NBA API returns newest first — keep that order for head() calls
    df = df.copy()
    df["PRA"] = df["PTS"] + df["REB"] + df["AST"]
    if not pd.api.types.is_datetime64_any_dtype(df["GAME_DATE"]):
        parsed = pd.to_datetime(df["GAME_DATE"], format="%b %d, %Y", errors="coerce")
        if parsed.isna().any():
            parsed = pd.to_datetime(df["GAME_DATE"])
        df["GAME_DATE"] = parsed

    # Days since last game (for rest context)
    days_rest = (pd.Timestamp.now() - df["GAME_DATE"].iloc[0]).days

    result = {}
    stat_map = {"pra": "PRA", "pts": "PTS", "reb": "REB", "ast": "AST"}

    for key, col in stat_map.items():
        vals = df[col]
        l5  = vals.head(5)
        l10 = vals.head(10) if len(vals) >= 10 else vals

        l5_avg     = float(l5.mean())
        l10_avg    = float(l10.mean())
        season_avg = float(vals.mean())
        std_l5     = float(l5.std()) if len(l5) > 1 else 0.0

        label = key.upper()
        # Each reason is {"text": str, "positive": bool}
        # positive=True  → factor pushes stats UP  (supports OVER)
        # positive=False → factor pushes stats DOWN (supports UNDER)
        reasons = []

        # 1 — Recent form vs season avg determines direction
        reasons.append({
            "text": f"Averaging {l5_avg:.1f} {label} over last 5 games",
            "positive": l5_avg >= season_avg,
        })

        # 2 — Trend vs 10-game average
        trend = l5_avg - l10_avg
        if abs(trend) >= 1.0:
            direction = "up" if trend > 0 else "down"
            reasons.append({
                "text": f"Trending {direction} ({trend:+.1f} vs 10-game avg of {l10_avg:.1f})",
                "positive": trend > 0,
            })
        else:
            reasons.append({
                "text": f"Consistent with 10-game average ({l10_avg:.1f})",
                "positive": l10_avg >= season_avg,
            })

        # 3 — vs season average
        vs_season = l5_avg - season_avg
        if abs(vs_season) >= 1.5:
            direction = "above" if vs_season > 0 else "below"
            reasons.append({
                "text": f"{abs(vs_season):.1f} pts {direction} season average ({season_avg:.1f})",
                "positive": vs_season > 0,
            })

        # 4 — Rest / schedule load
        if days_rest <= 1:
            reasons.append({
                "text": "Back-to-back game — potential fatigue factor",
                "positive": False,
            })
        elif days_rest >= 4:
            reasons.append({
                "text": f"{days_rest} days rest — well rested",
                "positive": True,
            })
        else:
            reasons.append({
                "text": f"{days_rest} day{'s' if days_rest != 1 else ''} rest since last game",
                "positive": True,
            })

        # 5 — Consistency
        if std_l5 < 4.0:
            reasons.append({
                "text": f"Very consistent recently (±{std_l5:.1f} game-to-game)",
                "positive": True,
            })
        elif std_l5 > 9.0:
            reasons.append({
                "text": f"High variance recently (±{std_l5:.1f} — streaky)",
                "positive": False,
            })
        else:
            reasons.append({
                "text": f"Moderate consistency recently (±{std_l5:.1f})",
                "positive": True,
            })

        result[key] = reasons[:5]

    return result


def make_prediction(
    full_log: pd.DataFrame,
    season: dict,
    model_data: dict = None,
    next_game: dict = None,
) -> dict:
    """
    Generate PRA prediction using the trained model.

    Uses the full game log so that rolling features (L3/L5/L10) are computed
    correctly instead of being approximated with a single average.

    `next_game`, when supplied, carries the context of the game actually being
    predicted -- {"is_home": bool, "days_rest": int}. Without it the last row of
    the log is used as-is, which means IS_HOME/DAYS_REST/IS_B2B describe the
    player's *previous* game rather than the upcoming one. The rolling stats are
    correct either way; only the three context features are affected.
    """

    # --- Fallback path (no model or no season stats) ---
    if model_data is None or season is None:
        recent_pra = (full_log["PTS"] + full_log["REB"] + full_log["AST"]).head(5).mean()
        season_pra = (
            season["points"] + season["rebounds"] + season["assists"]
            if season else recent_pra
        )
        pra = recent_pra * 0.6 + season_pra * 0.4

        pts_r = season["points"]  / (season_pra or 1) if season else 0.6
        reb_r = season["rebounds"]/ (season_pra or 1) if season else 0.2
        ast_r = season["assists"] / (season_pra or 1) if season else 0.2

        return {
            "points":    round(pra * pts_r, 1),
            "rebounds":  round(pra * reb_r, 1),
            "assists":   round(pra * ast_r, 1),
            "total_pra": round(pra, 1),
            "confidence": 55,
        }

    try:
        model        = model_data["model"]
        feature_cols = model_data.get("feature_cols", FEATURE_COLS)
        val_mae      = model_data.get("val_mae", 6.0)

        # Engineer features from the full log
        featured = engineer_features(full_log)
        if featured is None or len(featured) == 0:
            raise ValueError("engineer_features returned empty DataFrame")

        # The last row represents features we would use to predict the *next* game
        last_row = featured.iloc[[-1]].copy()

        # Overwrite the context features with the upcoming game's own context.
        if next_game:
            days_rest = float(min(max(next_game.get("days_rest", 3), 0), 7))
            last_row["IS_HOME"] = 1 if next_game.get("is_home") else 0
            last_row["DAYS_REST"] = days_rest
            last_row["IS_B2B"] = 1 if days_rest == 1 else 0

        X = last_row[feature_cols]

        predicted_pra = float(model.predict(X)[0])
        predicted_pra = max(predicted_pra, 0)

        # Distribute PRA using player's season ratios
        season_total = season["points"] + season["rebounds"] + season["assists"]
        if season_total > 0:
            pts_ratio = season["points"]   / season_total
            reb_ratio = season["rebounds"] / season_total
            ast_ratio = season["assists"]  / season_total
        else:
            pts_ratio, reb_ratio, ast_ratio = 0.6, 0.2, 0.2

        # Confidence: tighter when model error is small relative to predicted PRA
        confidence = max(50, min(90, int(75 - (val_mae / max(predicted_pra, 1)) * 100)))

        return {
            "points":    round(predicted_pra * pts_ratio, 1),
            "rebounds":  round(predicted_pra * reb_ratio, 1),
            "assists":   round(predicted_pra * ast_ratio, 1),
            "total_pra": round(predicted_pra, 1),
            "confidence": confidence,
        }

    except Exception as e:
        print(f"Prediction error: {e}")
        # Fallback to L5 average
        l5_pra = (full_log["PTS"] + full_log["REB"] + full_log["AST"]).head(5).mean()
        season_total = (
            season["points"] + season["rebounds"] + season["assists"]
            if season else l5_pra
        )
        pts_r = season["points"]   / (season_total or 1) if season else 0.6
        reb_r = season["rebounds"] / (season_total or 1) if season else 0.2
        ast_r = season["assists"]  / (season_total or 1) if season else 0.2

        return {
            "points":    round(l5_pra * pts_r, 1),
            "rebounds":  round(l5_pra * reb_r, 1),
            "assists":   round(l5_pra * ast_r, 1),
            "total_pra": round(l5_pra, 1),
            "confidence": 55,
        }
