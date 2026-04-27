from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
import pickle
import pandas as pd
import numpy as np
import sys
import os
import time
import requests
from datetime import datetime

# Add scripts to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from fetch_data import (
    search_player, get_player_game_log,
    get_todays_games_structured, get_team_roster,
)
from train_model import engineer_features, FEATURE_COLS
from nba_api.stats.static import players as nba_players_static

# ---------------------------------------------------------------------------
# Simple in-memory TTL cache  (player_id -> (fetched_at, data))
# ---------------------------------------------------------------------------
_stats_cache: dict = {}
CACHE_TTL = 300  # seconds (5 minutes)

def _cache_get(player_id: int):
    entry = _stats_cache.get(player_id)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL:
        return entry["data"]
    return None

def _cache_set(player_id: int, data: dict):
    _stats_cache[player_id] = {"ts": time.time(), "data": data}


# ---------------------------------------------------------------------------
# Injury report cache  (ESPN public API, 1-hour TTL)
# ---------------------------------------------------------------------------
_injury_cache: dict = {"ts": 0.0, "data": {}}
INJURY_TTL = 3600

def _fetch_injuries() -> dict:
    """Return {player_name_lower: {status, description}} from ESPN injury API."""
    if time.time() - _injury_cache["ts"] < INJURY_TTL:
        return _injury_cache["data"]
    try:
        url = "http://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        raw = resp.json()

        result: dict = {}
        for team_entry in raw.get("injuries", []):
            for inj in team_entry.get("injuries", []):
                name = inj.get("athlete", {}).get("displayName", "")
                status = inj.get("status", "")
                # Skip "Active" / empty — only real injury statuses
                if not name or not status or status.lower() in ("active", ""):
                    continue
                details = inj.get("details", {})
                injury_type = details.get("type", "")
                description = injury_type or status
                result[name.lower()] = {"status": status, "description": description}

        _injury_cache["ts"] = time.time()
        _injury_cache["data"] = result
        print(f"Injury report refreshed: {len(result)} players listed")
        return result
    except Exception as e:
        print(f"Injury fetch error: {e}")
        return _injury_cache["data"]  # Return stale data on error


# ---------------------------------------------------------------------------
# Defense ratings cache  (nba_api opponent stats, 6-hour TTL)
# ---------------------------------------------------------------------------
_defense_cache: dict = {"ts": 0.0, "data": {}}
DEFENSE_TTL = 21600

def _fetch_defense_ratings(season: str = "2025-26") -> dict:
    """Defense ratings via stats.nba.com — returns cached or empty if unavailable."""
    if time.time() - _defense_cache["ts"] < DEFENSE_TTL:
        return _defense_cache["data"]
    # stats.nba.com is often blocked; return stale data rather than hanging
    return _defense_cache["data"]

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

class TeamInfo(BaseModel):
    id: int
    name: str
    city: str
    abbreviation: str
    record: str

class Game(BaseModel):
    game_id: str
    status: str
    home_team: TeamInfo
    away_team: TeamInfo

class RosterPlayer(BaseModel):
    id: int
    name: str
    number: str
    position: str


# ============ ENDPOINTS ============

@app.get("/")
def root():
    return {"message": "NBA PRA Predictor API", "status": "running"}


@app.get("/players/search", response_model=List[Player])
def search_players(q: str = Query(min_length=2, max_length=50)):
    results = search_player(q.strip())
    return results[:10]


@app.get("/players/{player_id}/stats")
def get_player_stats(player_id: int):
    """Get player stats and prediction (one API call, cached for 5 min)."""

    cached = _cache_get(player_id)
    if cached:
        return cached

    # Single API call — derive everything from this one DataFrame
    full_log = get_player_game_log(player_id)
    if full_log is None or len(full_log) == 0:
        # Serve stale cache if available rather than hard-erroring
        stale = _stats_cache.get(player_id)
        if stale:
            print(f"Serving stale cache for player {player_id} due to rate limit")
            return stale["data"]
        raise HTTPException(status_code=503, detail="NBA API is currently rate-limited — please wait a few minutes and try again.")

    # Season averages derived from the DataFrame (no extra API call)
    season = _season_averages_from_log(full_log)

    # Recent 5 games derived from the DataFrame (no extra API call)
    recent_games, last_5_avg = _recent_stats_from_log(full_log, num_games=5)

    prediction = make_prediction(full_log, season)

    # Static lookup — no API call, just an in-memory dict
    player_info = nba_players_static.find_player_by_id(player_id)

    last_20_games, _ = _recent_stats_from_log(full_log, num_games=20)
    reasons = _compute_reasons(full_log)

    result = {
        "player": player_info,
        "prediction": prediction,
        "recent_games": recent_games,
        "last_20_games": last_20_games,
        "last_5_avg": last_5_avg,
        "season_avg": season,
        "reasons": reasons,
    }
    _cache_set(player_id, result)
    return result


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
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"])

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


@app.get("/injuries")
def get_injuries():
    """Current NBA injury report keyed by player name (cached 1 hour)."""
    return _fetch_injuries()


@app.get("/teams/defense-ratings")
def get_defense_ratings():
    """Opponent stats per team — how many PTS/REB/AST each team allows (cached 6 hours)."""
    return _fetch_defense_ratings()


@app.get("/games/today", response_model=List[Game])
def get_today_games():
    """Get all NBA games scheduled for today."""
    return get_todays_games_structured()


@app.get("/teams/{team_id}/players", response_model=List[RosterPlayer])
def get_roster(team_id: int):
    """Get the roster for a team."""
    return get_team_roster(team_id)


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "model_loaded": model_data is not None
    }