"""
Train an XGBoost model to predict player PRA (Points + Rebounds + Assists)

Pipeline:
  1. Fetch game logs for a diverse set of players
  2. Engineer rolling features
  3. Chronological 3-way split (70 / 15 / 15) per player
  4. Evaluate a naive baseline (L5 rolling average)
  5. Compare Ridge, RandomForest, and XGBoost on the validation set
  6. Tune hyperparameters for the best model on the validation set
  7. Final unbiased evaluation on the held-out test set
  8. Save model + metadata to disk
"""

from nba_api.stats.static import players
from nba_api.stats.endpoints import playergamelog
import pandas as pd
import numpy as np
import time
import pickle
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import ParameterGrid
import xgboost as xgb
from datetime import datetime
import os

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def safe_request(func, *args, **kwargs):
    time.sleep(0.7)
    return func(*args, **kwargs)


def get_player_full_game_log(player_id: int, season: str = "2025-26"):
    """Fetch a full season game log for one player."""
    try:
        game_log = safe_request(
            playergamelog.PlayerGameLog,
            player_id=player_id,
            season=season,
        )
        df = game_log.get_data_frames()[0]
        df["PLAYER_ID"] = player_id
        return df
    except Exception as e:
        print(f"  Error fetching player {player_id}: {e}")
        return None


# ---------------------------------------------------------------------------
# Feature engineering  (also imported by main.py for live predictions)
# ---------------------------------------------------------------------------

def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build rolling and contextual features from a raw game-log DataFrame.

    Returns None if there are fewer than 10 rows after processing.
    """
    if df is None or len(df) < 10:
        return None

    # Sort oldest → newest so rolling windows look backward in time
    df = df.sort_values("GAME_DATE").reset_index(drop=True)

    # Target
    df["PRA"] = df["PTS"] + df["REB"] + df["AST"]

    # Context features
    df["IS_HOME"] = df["MATCHUP"].apply(lambda x: 1 if "vs." in x else 0)
    df["OPPONENT"] = df["MATCHUP"].apply(lambda x: x.split()[-1])

    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"])
    df["DAYS_REST"] = df["GAME_DATE"].diff().dt.days.fillna(3).clip(0, 7)

    # Rolling averages for each stat (shift(1) so we never leak the current game)
    for stat in ["PTS", "REB", "AST", "PRA", "MIN"]:
        df[f"{stat}_L3"]     = df[stat].shift(1).rolling(window=3,  min_periods=1).mean()
        df[f"{stat}_L5"]     = df[stat].shift(1).rolling(window=5,  min_periods=1).mean()
        df[f"{stat}_L10"]    = df[stat].shift(1).rolling(window=10, min_periods=1).mean()
        df[f"{stat}_SEASON"] = df[stat].shift(1).expanding().mean()

    # Momentum: wins in last 5 games
    df["WIN"]        = (df["WL"] == "W").astype(int)
    df["WIN_STREAK"] = df["WIN"].shift(1).rolling(window=5, min_periods=1).sum()

    df = df.dropna()
    return df


FEATURE_COLS = [
    "IS_HOME", "DAYS_REST",
    "PTS_L3", "PTS_L5", "PTS_L10", "PTS_SEASON",
    "REB_L3", "REB_L5", "REB_L10", "REB_SEASON",
    "AST_L3", "AST_L5", "AST_L10", "AST_SEASON",
    "PRA_L3", "PRA_L5", "PRA_L10", "PRA_SEASON",
    "MIN_L3", "MIN_L5", "MIN_L10", "MIN_SEASON",
    "WIN_STREAK",
]


# ---------------------------------------------------------------------------
# Chronological split
# ---------------------------------------------------------------------------

def chronological_split(df: pd.DataFrame, train_frac=0.70, val_frac=0.15):
    """
    Split a player's game log chronologically into train / val / test.
    Games are already sorted oldest → newest by engineer_features.
    """
    n = len(df)
    train_end = int(n * train_frac)
    val_end   = int(n * (train_frac + val_frac))
    return df.iloc[:train_end], df.iloc[train_end:val_end], df.iloc[val_end:]


def prepare_splits(player_ids: list, season: str = "2025-26"):
    """
    Fetch + engineer features for every player, then split and pool.

    Returns:
        (X_train, y_train, X_val, y_val, X_test, y_test)
    """
    train_frames, val_frames, test_frames = [], [], []

    for i, pid in enumerate(player_ids):
        print(f"  [{i+1}/{len(player_ids)}] player_id={pid}")
        raw = get_player_full_game_log(pid, season)
        if raw is None:
            continue
        featured = engineer_features(raw)
        if featured is None or len(featured) < 15:
            print(f"    Skipped — too few rows after engineering")
            continue

        tr, va, te = chronological_split(featured)
        if len(tr) < 5 or len(va) < 2 or len(te) < 2:
            print(f"    Skipped — split produced empty partition")
            continue

        train_frames.append(tr)
        val_frames.append(va)
        test_frames.append(te)

    if not train_frames:
        raise RuntimeError("No usable player data collected.")

    def pool(frames):
        combined = pd.concat(frames, ignore_index=True)
        X = combined[FEATURE_COLS]
        y = combined["PRA"]
        return X, y

    X_train, y_train = pool(train_frames)
    X_val,   y_val   = pool(val_frames)
    X_test,  y_test  = pool(test_frames)

    print(f"\n  Train: {len(X_train)} samples  |  Val: {len(X_val)}  |  Test: {len(X_test)}")
    return X_train, y_train, X_val, y_val, X_test, y_test


# ---------------------------------------------------------------------------
# Metrics helper
# ---------------------------------------------------------------------------

def report(name, y_true, y_pred):
    mae  = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    r2   = r2_score(y_true, y_pred)
    print(f"  {name:<28}  MAE={mae:.2f}  RMSE={rmse:.2f}  R²={r2:.3f}")
    return mae, rmse, r2


# ---------------------------------------------------------------------------
# Step 3 — Baseline
# ---------------------------------------------------------------------------

def evaluate_baseline(X_val, y_val):
    print("\n[Step 3] Baseline — predict PRA_L5 rolling average")
    preds = X_val["PRA_L5"].values
    return report("Baseline (L5 avg)", y_val, preds)


# ---------------------------------------------------------------------------
# Step 4 & 5 — Train XGBoost with early stopping, check for overfitting
# ---------------------------------------------------------------------------

def train_xgboost(X_train, y_train, X_val, y_val, params=None):
    if params is None:
        params = dict(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            objective="reg:squarederror",
            random_state=42,
            early_stopping_rounds=20,
            eval_metric="mae",
        )

    model = xgb.XGBRegressor(**params)
    model.fit(
        X_train, y_train,
        eval_set=[(X_train, y_train), (X_val, y_val)],
        verbose=False,
    )

    train_mae = mean_absolute_error(y_train, model.predict(X_train))
    val_mae   = mean_absolute_error(y_val,   model.predict(X_val))
    print(f"  XGBoost  train_MAE={train_mae:.2f}  val_MAE={val_mae:.2f}", end="")
    if val_mae > train_mae * 1.3:
        print("  ⚠ possible overfitting")
    elif val_mae < train_mae * 1.1 and val_mae > 8:
        print("  ⚠ possible underfitting")
    else:
        print("  ✓ looks healthy")

    return model, val_mae


# ---------------------------------------------------------------------------
# Step 6 — Compare models
# ---------------------------------------------------------------------------

def compare_models(X_train, y_train, X_val, y_val):
    print("\n[Step 6] Model comparison on validation set")
    results = {}

    # Ridge Regression
    ridge = Ridge(alpha=1.0)
    ridge.fit(X_train, y_train)
    mae, _, _ = report("Ridge Regression", y_val, ridge.predict(X_val))
    results["ridge"] = (ridge, mae)

    # Random Forest
    rf = RandomForestRegressor(n_estimators=100, max_depth=8, random_state=42, n_jobs=-1)
    rf.fit(X_train, y_train)
    mae, _, _ = report("Random Forest", y_val, rf.predict(X_val))
    results["random_forest"] = (rf, mae)

    # XGBoost (default params)
    print("\n[Step 4 & 5] XGBoost initial training + overfitting check")
    xgb_model, xgb_mae = train_xgboost(X_train, y_train, X_val, y_val)
    report("XGBoost (default)", y_val, xgb_model.predict(X_val))
    results["xgboost"] = (xgb_model, xgb_mae)

    best_name = min(results, key=lambda k: results[k][1])
    print(f"\n  Best model on val set: {best_name} (MAE={results[best_name][1]:.2f})")
    return results, best_name


# ---------------------------------------------------------------------------
# Step 7 — Hyperparameter tuning (XGBoost grid)
# ---------------------------------------------------------------------------

def tune_xgboost(X_train, y_train, X_val, y_val):
    print("\n[Step 7] Hyperparameter tuning (XGBoost)")

    param_grid = {
        "n_estimators":    [200, 300],
        "max_depth":       [3, 4, 5],
        "learning_rate":   [0.05, 0.1],
        "subsample":       [0.8, 1.0],
        "colsample_bytree":[0.8, 1.0],
    }

    best_mae    = float("inf")
    best_params = None
    total       = len(list(ParameterGrid(param_grid)))
    print(f"  Searching {total} combinations...")

    for i, params in enumerate(ParameterGrid(param_grid), 1):
        params.update(
            dict(objective="reg:squarederror", random_state=42,
                 early_stopping_rounds=20, eval_metric="mae")
        )
        model = xgb.XGBRegressor(**params)
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )
        mae = mean_absolute_error(y_val, model.predict(X_val))
        if mae < best_mae:
            best_mae    = mae
            best_params = params.copy()
            print(f"  [{i}/{total}] New best  MAE={mae:.2f}  params={params}")

    print(f"\n  Best val MAE after tuning: {best_mae:.2f}")
    print(f"  Best params: {best_params}")
    return best_params, best_mae


# ---------------------------------------------------------------------------
# Step 8 — Final retrain on train+val, evaluate on test
# ---------------------------------------------------------------------------

def final_model(X_train, y_train, X_val, y_val, X_test, y_test, best_params):
    print("\n[Step 8] Retrain on train+val, evaluate on held-out test set")

    X_tv = pd.concat([X_train, X_val])
    y_tv = pd.concat([y_train, y_val])

    # Remove early_stopping for final fit (no eval set)
    params = {k: v for k, v in best_params.items()
              if k not in ("early_stopping_rounds", "eval_metric")}

    model = xgb.XGBRegressor(**params)
    model.fit(X_tv, y_tv, verbose=False)

    test_mae, test_rmse, test_r2 = report("Final model (test set)", y_test, model.predict(X_test))

    print("\n  Top 10 feature importances:")
    imp = (
        pd.DataFrame({"feature": FEATURE_COLS,
                      "importance": model.feature_importances_})
        .sort_values("importance", ascending=False)
    )
    for _, row in imp.head(10).iterrows():
        print(f"    {row['feature']:<22} {row['importance']:.3f}")

    return model, test_mae, test_rmse, test_r2


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_model(model, best_params, baseline_mae, best_val_mae,
               test_mae, n_players, n_train,
               path="models/pra_model.pkl"):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    payload = {
        "model":        model,
        "feature_cols": FEATURE_COLS,
        "best_params":  best_params,
        "baseline_mae": round(float(baseline_mae), 3),
        "val_mae":      round(float(best_val_mae), 3),
        "test_mae":     round(float(test_mae), 3),
        "n_players":    n_players,
        "n_train":      n_train,
        "trained_at":   datetime.now().isoformat(),
    }

    with open(path, "wb") as f:
        pickle.dump(payload, f)

    print(f"\n  Model saved to {path}")
    print(f"  baseline_MAE={baseline_mae:.2f}  val_MAE={best_val_mae:.2f}  test_MAE={test_mae:.2f}")


# ---------------------------------------------------------------------------
# Player pool — diverse roles and usage levels
# ---------------------------------------------------------------------------

TRAINING_PLAYERS = [
    # Guards
    201939,  # Stephen Curry
    1628983, # Shai Gilgeous-Alexander
    1629029, # Luka Doncic
    203076,  # Anthony Davis (big, but high usage)
    203081,  # Damian Lillard
    1629627, # Trae Young
    1629630, # Ja Morant
    1630173, # LaMelo Ball
    203914,  # Zach LaVine
    # Wings / forwards
    1628369, # Jayson Tatum
    203507,  # Giannis Antetokounmpo
    2544,    # LeBron James
    1630162, # Anthony Edwards
    1629645, # RJ Barrett
    203954,  # Joel Embiid
    1629029, # Luka Doncic (also wing-like)
    202331,  # Paul George
    # Bigs / centers
    203999,  # Nikola Jokic
    1629627, # Already listed — skip duplicates in practice
    203497,  # Rudy Gobert
    203954,  # Joel Embiid (duplicate removed at runtime)
    1629029, # Luka
    1630585, # Evan Mobley
    1630578, # Scottie Barnes
    1629628, # Jaren Jackson Jr.
]

# Deduplicate while preserving order
_seen = set()
TRAINING_PLAYERS = [
    pid for pid in TRAINING_PLAYERS
    if pid not in _seen and not _seen.add(pid)
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("NBA PRA Predictor — Full ML Pipeline")
    print("=" * 60)

    season = "2025-26"
    print(f"\n[Step 2] Collecting data for {len(TRAINING_PLAYERS)} players (season {season})...")
    print("  (This takes a few minutes due to API rate limits)\n")

    X_train, y_train, X_val, y_val, X_test, y_test = prepare_splits(
        TRAINING_PLAYERS, season=season
    )

    # Step 3 — Baseline
    baseline_mae, _, _ = evaluate_baseline(X_val, y_val)

    # Step 6 — Compare models (includes steps 4 & 5 for XGBoost)
    results, best_name = compare_models(X_train, y_train, X_val, y_val)

    # Step 7 — Tune XGBoost (always tune XGBoost; swap if another model won)
    if best_name == "xgboost":
        best_params, best_val_mae = tune_xgboost(X_train, y_train, X_val, y_val)
    else:
        print(f"\n[Step 7] {best_name} beat XGBoost — tuning {best_name} instead")
        # For Ridge/RF, just use the already-fit model; skip grid search
        best_model, best_val_mae = results[best_name]
        best_params = {}

    # Step 8 — Final test evaluation
    if best_name == "xgboost" or best_params:
        model, test_mae, test_rmse, test_r2 = final_model(
            X_train, y_train, X_val, y_val, X_test, y_test, best_params
        )
    else:
        # Non-XGBoost winner: retrain on train+val
        best_model_cls = Ridge if best_name == "ridge" else RandomForestRegressor
        X_tv = pd.concat([X_train, X_val])
        y_tv = pd.concat([y_train, y_val])
        model = best_model_cls()
        model.fit(X_tv, y_tv)
        test_mae, test_rmse, test_r2 = report(
            "Final model (test set)", y_test, model.predict(X_test)
        )
        best_params = {}

    # Save
    save_model(
        model=model,
        best_params=best_params,
        baseline_mae=baseline_mae,
        best_val_mae=best_val_mae,
        test_mae=test_mae,
        n_players=len(TRAINING_PLAYERS),
        n_train=len(X_train),
        path="models/pra_model.pkl",
    )

    print("\n" + "=" * 60)
    print("Pipeline complete!")
    print(f"  Baseline MAE : {baseline_mae:.2f} PRA pts")
    print(f"  Best val MAE : {best_val_mae:.2f} PRA pts")
    print(f"  Test MAE     : {test_mae:.2f} PRA pts")
    if test_mae < baseline_mae:
        print(f"  Model beats baseline by {baseline_mae - test_mae:.2f} pts ✓")
    else:
        print("  ⚠ Model does NOT beat baseline — consider adding more data or features")
    print("=" * 60)
