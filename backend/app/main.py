from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import pickle
import pandas as pd
import numpy as np
import sys
import os
from datetime import datetime

# Add scripts to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from fetch_data import search_player, get_player_recent_stats, get_season_averages, get_player_game_log
from train_model import engineer_features, FEATURE_COLS

app = FastAPI(
    title="NBA PRA Predictor API",
    description="ML-powered NBA player stat predictions",
    version="1.0.0"
)

# Allow CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load trained model
MODEL_PATH = os.path.join(os.path.dirname(__file__), '..', 'models', 'pra_model.pkl')

def load_model():
    try:
        with open(MODEL_PATH, 'rb') as f:
            return pickle.load(f)
    except FileNotFoundError:
        print("Warning: Model not found. Predictions will use averages.")
        return None

model_data = load_model()


# ============ PYDANTIC MODELS ============

class Player(BaseModel):
    id: int
    full_name: str
    first_name: str
    last_name: str
    is_active: bool

class GameLog(BaseModel):
    date: str
    opponent: str
    home: bool
    points: int
    rebounds: int
    assists: int
    minutes: int
    result: str

class Prediction(BaseModel):
    points: float
    rebounds: float
    assists: float
    total_pra: float
    confidence: int

class PlayerStats(BaseModel):
    player: Player
    prediction: Prediction
    recent_games: List[GameLog]
    last_5_avg: dict
    season_avg: dict


# ============ ENDPOINTS ============

@app.get("/")
def root():
    return {"message": "NBA PRA Predictor API", "status": "running"}


@app.get("/players/search", response_model=List[Player])
def search_players(q: str):
    """Search for players by name"""
    if len(q) < 2:
        return []
    
    results = search_player(q)
    return results[:10]  # Limit to 10 results


@app.get("/players/{player_id}/stats")
def get_player_stats(player_id: int):
    """Get player stats and prediction"""

    # Full game log needed for proper feature engineering
    full_log = get_player_game_log(player_id)
    if full_log is None or len(full_log) == 0:
        raise HTTPException(status_code=404, detail="Player not found or no recent games")

    # Recent 5 games for display
    recent = get_player_recent_stats(player_id, num_games=5)
    if recent is None:
        raise HTTPException(status_code=404, detail="Player not found or no recent games")

    season = get_season_averages(player_id)

    prediction = make_prediction(full_log, season)

    players_list = search_player("")
    player_info = next((p for p in players_list if p['id'] == player_id), None)

    return {
        "player": player_info,
        "prediction": prediction,
        "recent_games": recent['recent_games'],
        "last_5_avg": recent['averages'],
        "season_avg": season,
    }


def make_prediction(full_log: pd.DataFrame, season: dict) -> dict:
    """
    Generate PRA prediction using the trained model.

    Uses the full game log so that rolling features (L3/L5/L10) are computed
    correctly instead of being approximated with a single average.
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
        last_row = featured.iloc[[-1]]
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


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "model_loaded": model_data is not None
    }