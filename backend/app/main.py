"""
NBA PRA Predictor API.

Every endpoint is served from a prebuilt SQLite snapshot (see app/store.py and
scripts/build_snapshot.py). Nothing here contacts stats.nba.com, cdn.nba.com or
ESPN at request time.

That is a deliberate architectural constraint, not an optimisation. The NBA
rate-limits its stats endpoints aggressively and IP-blocks datacenter ranges
(AWS/GCP/Azure/Render/Vercel), so an API that scrapes on demand is both slow and
impossible to host for free. Moving all fetching into a daily offline job makes
the request path fast, deployable, and unable to fail because an upstream
provider throttled us.
"""

import os
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import store


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        store.load()
    except store.SnapshotUnavailable as e:
        # Start anyway so /health can explain what is wrong instead of the
        # process crash-looping on a host with no snapshot.
        print(f"WARNING: {e}")
    yield


app = FastAPI(
    title="NBA PRA Predictor API",
    description="ML-powered NBA player stat predictions, served from a daily snapshot",
    version="2.0.0",
    lifespan=lifespan,
)

# Comma-separated so a deployed frontend can be added without a code change.
CORS_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


def _require_snapshot():
    """503 with an actionable message when no snapshot is loaded."""
    try:
        store.meta()
        store._db()
    except store.SnapshotUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


# ============ ENDPOINTS ============

@app.get("/")
def root():
    return {"message": "NBA PRA Predictor API", "status": "running"}


@app.get("/players/search", response_model=List[Player])
def search_players(q: str = Query(min_length=2, max_length=50)):
    _require_snapshot()
    return store.search_players(q.strip())


@app.get("/players/{player_id}/stats")
def get_player_stats(player_id: int):
    """
    Player stats and prediction.

    The payload was computed by the daily job using the same code this API used
    to run inline (app/predict.py), so this is a single indexed read. The old
    "NBA API is currently rate-limited" 503 is gone because there is no longer
    an upstream call that can be rate-limited.
    """
    _require_snapshot()

    payload = store.get_prediction(player_id)
    if payload is not None:
        return payload

    if store.player_exists(player_id):
        raise HTTPException(
            status_code=404,
            detail="Not enough recent games for this player to generate a prediction.",
        )
    raise HTTPException(status_code=404, detail="Player not found.")


@app.get("/injuries")
def get_injuries():
    """Current NBA injury report keyed by lowercase player name."""
    _require_snapshot()
    return store.get_injuries()


@app.get("/teams/defense-ratings")
def get_defense_ratings():
    """
    PTS/REB/AST each team allows per game, with ranks (1 = stingiest).

    Computed from the same box scores the predictions use. The previous
    implementation returned {} unconditionally because stats.nba.com was
    unreachable, leaving the opponent-defense UI permanently blank.
    """
    _require_snapshot()
    return store.get_defense_ratings()


@app.get("/games/today", response_model=List[Game])
def get_today_games():
    _require_snapshot()
    return store.get_games()


@app.get("/games/upcoming", response_model=List[Game])
def get_upcoming_games(limit: int = Query(default=20, ge=1, le=100)):
    """Next scheduled games — useful on an off day, when /games/today is empty."""
    _require_snapshot()
    return store.get_upcoming_games(limit)


@app.get("/teams/{team_id}/players", response_model=List[RosterPlayer])
def get_roster(team_id: int):
    _require_snapshot()
    return store.get_roster(team_id)


@app.get("/health")
def health_check():
    try:
        meta = store.meta()
        store._db()
    except store.SnapshotUnavailable as e:
        return {"status": "degraded", "snapshot_loaded": False, "detail": str(e)}

    age = store.age_hours()
    return {
        "status": "healthy",
        "snapshot_loaded": True,
        "snapshot_built_at": meta.get("built_at"),
        "snapshot_age_hours": round(age, 2) if age is not None else None,
        "stale": store.is_stale(),
        "n_players": int(meta.get("n_players", 0)),
        "n_predictions": int(meta.get("n_predictions", 0)),
        "data_through": meta.get("parquet_max_game_date"),
        "model_trained_at": meta.get("model_trained_at"),
        "source_years": meta.get("source_years"),
    }
