"""
Train a model to predict player PRA (Points + Rebounds + Assists).

Compares Ridge, RandomForest and XGBoost and keeps whichever wins on the
validation set -- so despite the name, the saved artifact is not necessarily
XGBoost. Check `model_type` in the pickle.

Pipeline:
  1. Load every player's game log from the free bulk parquet
  2. Engineer rolling features
  3. Chronological 3-way split (70 / 15 / 15) by date across the league
  4. Evaluate a naive baseline (L5 rolling average)
  5. Compare Ridge, RandomForest, and XGBoost on the validation set
  6. Tune hyperparameters for the best model on the validation set
  7. Final unbiased evaluation on the held-out test set
  8. Save model + metadata to disk
"""

import pandas as pd
import numpy as np
import pickle
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import ParameterGrid
import xgboost as xgb
from datetime import datetime
import os
import sys

# ---------------------------------------------------------------------------
# Training data now comes from the free bulk parquet (see build_training_frame).
# The old stats.nba.com scraping helpers -- CUSTOM_HEADERS, safe_request and
# get_player_full_game_log -- and the 47-player hardcoded TRAINING_PLAYERS pool
# were removed with them. Every player with enough games is now used.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------
# Moved to app/features.py so the API can import it without pulling in xgboost
# and sklearn.ensemble. Re-exported here so existing references keep working
# and train/serve parity is structural rather than a copy-paste promise.

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.features import (  # noqa: E402,F401
    engineer_features, FEATURE_COLS, OPP_FEATURE_COLS, ABSENCE_FEATURE_COLS,
    SHOT_FEATURE_COLS,
)



# ---------------------------------------------------------------------------
# Training data
# ---------------------------------------------------------------------------

def build_training_frame(years, min_games=20, with_opponent=False,
                         with_absence=False, with_shots=False):
    """
    Pool engineered features for every player with enough games, from the free
    bulk parquet.

    This replaces a loop that scraped 47 hardcoded player ids one at a time with
    a 1s sleep between calls. That took ~15 minutes, and rate limiting silently
    truncated it -- the shipped model recorded n_players=21 out of 47. Reading
    the bulk files takes seconds and covers the whole league.
    """
    from parquet_source import load_seasons
    from espn_adapter import (
        clean_box_scores, to_nba_gamelog, opponent_defense_history,
        team_absence_history, shot_quality_history,
    )

    print(f"  loading seasons {list(years)} ...")
    clean = clean_box_scores(load_seasons(years))

    hist = None
    if with_opponent:
        hist = opponent_defense_history(clean)
        print(f"  opponent defense history: {len(hist)} team-games")

    shots = None
    if with_shots:
        import json as _json
        from parquet_source import load_shots_seasons
        _idmap = _json.load(open(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "data", "id_map.json")))
        nba_to_espn = {v["player_id"]: int(k) for k, v in _idmap.items()
                       if v["source"] != "synthetic"}
        raw_shots = load_shots_seasons(years)
        if raw_shots is not None:
            shots = shot_quality_history(raw_shots, clean, nba_to_espn)
            print(f"  shot quality history: {len(shots)} player-games")

    absence = None
    if with_absence:
        absence = team_absence_history(clean)
        print(f"  teammate absence history: {len(absence)} team-games")

    frames = []
    kept = skipped = 0
    for espn_id, group in clean.groupby("athlete_id"):
        if len(group) < min_games:
            skipped += 1
            continue
        log = to_nba_gamelog(group, player_id=int(espn_id))
        featured = engineer_features(log, opp_history=hist, absence_history=absence,
                                     shot_history=shots)
        if featured is None or len(featured) < min_games:
            skipped += 1
            continue
        featured = featured.copy()
        featured["PLAYER_ID"] = int(espn_id)
        frames.append(featured)
        kept += 1

    if not frames:
        raise RuntimeError("No usable player data collected.")

    pooled = pd.concat(frames, ignore_index=True)
    print(f"  {kept} players kept, {skipped} skipped (<{min_games} usable games)")
    print(f"  {len(pooled)} player-games pooled")
    return pooled


def split_by_date(pooled: pd.DataFrame, feature_cols=None, train_frac=0.70, val_frac=0.15):
    """
    Split the pooled rows chronologically across the WHOLE league, not per
    player.

    Splitting inside each player's log lets the model train on games that happen
    after the ones it is tested on for a different player, which flatters the
    score. A single global date cut measures what the app actually does: predict
    a future game from past games only.

    Returns (X_train, y_train, X_val, y_val, X_test, y_test).
    """
    pooled = pooled.sort_values("GAME_DATE").reset_index(drop=True)
    dates = pooled["GAME_DATE"]

    train_cut = dates.quantile(train_frac)
    val_cut = dates.quantile(train_frac + val_frac)

    tr = pooled[dates <= train_cut]
    va = pooled[(dates > train_cut) & (dates <= val_cut)]
    te = pooled[dates > val_cut]

    print(f"\n  Train: {len(tr)} rows  (through {train_cut.date()})")
    print(f"  Val  : {len(va)} rows  ({train_cut.date()} -> {val_cut.date()})")
    print(f"  Test : {len(te)} rows  (after {val_cut.date()})")
    return tr, va, te


def xy(frames, feature_cols, target):
    """(X, y) per split for one target column -- PTS, REB, AST or PRA."""
    cols = feature_cols or FEATURE_COLS
    out = []
    for d in frames:
        out.extend([d[cols], d[target]])
    return out


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

def evaluate_baseline(X_val, y_val, target="PRA"):
    """Naive comparison: predict the player's own 5-game average of that stat."""
    print(f"\n  Baseline — predict {target}_L5 rolling average")
    preds = X_val[f"{target}_L5"].values
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
        # Use the columns actually trained on, not the module constant --
        # those differ whenever opponent features are enabled.
        pd.DataFrame({"feature": list(X_tv.columns),
                      "importance": model.feature_importances_})
        .sort_values("importance", ascending=False)
    )
    for _, row in imp.head(10).iterrows():
        print(f"    {row['feature']:<22} {row['importance']:.3f}")

    return model, test_mae, test_rmse, test_r2


# ---------------------------------------------------------------------------
# Train one target end to end
# ---------------------------------------------------------------------------

def train_target(target, frames, feature_cols):
    """
    Full pipeline for a single stat. Returns (model, metrics, params).

    Each of PTS / REB / AST gets its own model rather than being carved out of a
    PRA prediction by season ratios. Ratios assume a player's mix is constant,
    which is exactly wrong in the cases that matter -- a guard whose assists
    spike when the primary ball-handler sits keeps the same split under the old
    approach.
    """
    print("\n" + "=" * 60)
    print(f"TARGET: {target}")
    print("=" * 60)

    X_train, y_train, X_val, y_val, X_test, y_test = xy(frames, feature_cols, target)

    baseline_mae, _, _ = evaluate_baseline(X_val, y_val, target)
    results, best_name = compare_models(X_train, y_train, X_val, y_val)

    if best_name == "xgboost":
        best_params, best_val_mae = tune_xgboost(X_train, y_train, X_val, y_val)
        model, test_mae, _, _ = final_model(
            X_train, y_train, X_val, y_val, X_test, y_test, best_params
        )
    else:
        from sklearn.base import clone
        best_model, best_val_mae = results[best_name]
        model = clone(best_model)
        X_tv = pd.concat([X_train, X_val])
        y_tv = pd.concat([y_train, y_val])
        model.fit(X_tv, y_tv)
        best_params = {k: v for k, v in model.get_params().items()
                       if v is not None and not callable(v)}
        test_mae, _, _ = report(f"Final {target} model (test)", y_test,
                                model.predict(X_test))

    metrics = {
        "baseline_mae": round(float(baseline_mae), 3),
        "val_mae": round(float(best_val_mae), 3),
        "test_mae": round(float(test_mae), 3),
        "model_type": type(model).__name__,
    }
    return model, metrics, best_params


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_multi_model(models, metrics, params, feature_cols, path=None,
                     pra_source="sum", extra=None):
    """
    Persist one model per stat.

    Shape:
      models       {"PTS": est, "REB": est, "AST": est, "PRA": est}
      metrics      per-target baseline/val/test MAE
      pra_source   "sum"   -> total PRA is PTS+REB+AST from the three models
                   "model" -> total PRA comes from its own dedicated model
    """
    path = os.path.abspath(path or MODEL_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    payload = {
        "models": models,
        "metrics": metrics,
        "best_params": params,
        "feature_cols": list(feature_cols),
        "pra_source": pra_source,
        "targets": list(models.keys()),
        "trained_at": datetime.now().isoformat(),
    }
    payload.update(extra or {})

    with open(path, "wb") as f:
        pickle.dump(payload, f)

    print(f"\n  Saved {len(models)} models to {path}")
    for t, m in metrics.items():
        print(f"    {t:<4} baseline={m['baseline_mae']:.2f}  "
              f"val={m['val_mae']:.2f}  test={m['test_mae']:.2f}  ({m['model_type']})")


# PRA last: it is trained for comparison against the sum of the other three.
TARGETS = ["PTS", "REB", "AST", "PRA"]

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "models", "pra_model.pkl"
)

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, default=4,
                    help="how many seasons of history to train on")
    ap.add_argument("--min-games", type=int, default=20)
    ap.add_argument("--out", default=MODEL_PATH)
    ap.add_argument("--with-opponent", action="store_true",
                    help="add leakage-free opponent-strength features")
    ap.add_argument("--with-absence", action="store_true",
                    help="add missing-teammate-minutes feature")
    ap.add_argument("--with-shots", action="store_true",
                    help="add shot-location quality features")
    args = ap.parse_args()

    from parquet_source import latest_available_season

    print("=" * 60)
    print("NBA PRA Predictor — Full ML Pipeline")
    print("=" * 60)

    latest = latest_available_season()
    years = list(range(latest - args.seasons + 1, latest + 1))

    feature_cols = list(FEATURE_COLS)
    if args.with_opponent:
        feature_cols += OPP_FEATURE_COLS
    if args.with_absence:
        feature_cols += ABSENCE_FEATURE_COLS
    if args.with_shots:
        feature_cols += SHOT_FEATURE_COLS

    extras = ([" opponent"] if args.with_opponent else []) + \
             ([" absence"] if args.with_absence else []) + \
             ([" shots"] if args.with_shots else [])
    print(f"\n[Step 1] Building training set from bulk parquet {years}")
    print(f"  features: {len(feature_cols)}"
          + (f" (incl.{','.join(extras)})" if extras else ""))

    pooled = build_training_frame(years, min_games=args.min_games,
                                  with_opponent=args.with_opponent,
                                  with_absence=args.with_absence,
                                  with_shots=args.with_shots)
    n_players = pooled["PLAYER_ID"].nunique()
    frames = split_by_date(pooled, feature_cols=feature_cols)

    # PTS/REB/AST are the products; PRA is trained too so we can measure whether
    # summing the three beats predicting the total directly.
    models, metrics, params = {}, {}, {}
    for target in TARGETS:
        model, m, p = train_target(target, frames, feature_cols)
        models[target], metrics[target], params[target] = model, m, p

    # --- does summing the three beat the dedicated PRA model? ---
    _, _, _, _, X_test, _ = xy(frames, feature_cols, "PRA")
    y_pra = frames[2]["PRA"]
    summed = sum(models[t].predict(X_test) for t in ("PTS", "REB", "AST"))
    sum_mae = float(np.mean(np.abs(summed - y_pra.values)))
    direct_mae = metrics["PRA"]["test_mae"]

    print("\n" + "=" * 60)
    print("PRA: summed components vs dedicated model")
    print("=" * 60)
    print(f"  sum of PTS+REB+AST models : test MAE {sum_mae:.3f}")
    print(f"  dedicated PRA model       : test MAE {direct_mae:.3f}")

    # Prefer the sum unless the dedicated model is clearly better. Summing keeps
    # the headline PRA equal to the three numbers shown beside it; a dedicated
    # model that disagrees with its own components is confusing in the UI, so it
    # has to earn the inconsistency.
    pra_source = "sum" if sum_mae <= direct_mae + 0.05 else "model"
    print(f"  -> using: {pra_source}")

    metrics["PRA"]["sum_test_mae"] = round(sum_mae, 3)

    save_multi_model(
        models, metrics, params, feature_cols,
        path=os.path.abspath(args.out),
        pra_source=pra_source,
        extra={
            "data_source": "sportsdataverse bulk parquet",
            "seasons": ",".join(str(y) for y in years),
            "n_players": n_players,
            "n_rows": len(pooled),
            "n_train": len(frames[0]),
            "with_opponent": args.with_opponent,
            "with_absence": args.with_absence,
            "with_shots": args.with_shots,
            "sklearn_version": __import__("sklearn").__version__,
        },
    )

    print("\n" + "=" * 60)
    print("Pipeline complete")
    print(f"  Players : {n_players}   Rows: {len(pooled)}")
    for t in TARGETS:
        m = metrics[t]
        delta = m["baseline_mae"] - m["test_mae"]
        flag = "beats baseline" if delta > 0 else "WORSE than baseline"
        print(f"  {t:<4} test MAE {m['test_mae']:.2f}  vs baseline "
              f"{m['baseline_mae']:.2f}  ({delta:+.2f}, {flag})")
    print("=" * 60)
