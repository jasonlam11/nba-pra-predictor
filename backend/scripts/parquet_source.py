"""
Downloads and caches the free sportsdataverse bulk NBA box-score files.

Why this exists: the project used to scrape stats.nba.com through nba_api on
every request. That endpoint rate-limits hard and IP-blocks datacenter ranges
(AWS/GCP/Azure/Render/Vercel), so the app could not be deployed anywhere free
and a full training run took ~15 minutes of sleeping between calls.

These parquet files are published as GitHub Release assets: no API key, no rate
limit, reachable from any IP, and refreshed daily (~05:00 UTC) during the
season. One season is ~0.6 MB and holds every player-game, so a single download
replaces the entire scrape.

Source: https://github.com/sportsdataverse/sportsdataverse-data
"""

import os
import time
import urllib.request
import urllib.error

import pandas as pd

RELEASE_BASE = (
    "https://github.com/sportsdataverse/sportsdataverse-data/"
    "releases/download/espn_nba_player_boxscores"
)

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "raw")

# sportsdataverse labels a season by the calendar year it ENDS in:
# player_box_2026.parquet covers the 2025-26 season.
EARLIEST_SEASON = 2002


def season_url(year: int) -> str:
    return f"{RELEASE_BASE}/player_box_{year}.parquet"


def _download(year: int, dest: str) -> bool:
    """Fetch one season file. Returns False on 404 (season not published yet)."""
    url = season_url(year)
    tmp = dest + ".tmp"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "nba-pra-predictor"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as fh:
            fh.write(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise
    # Only replace the cached copy once the download completed, so an
    # interrupted run never leaves a truncated parquet behind.
    os.replace(tmp, dest)
    return True


def load_season(year: int, max_age_hours: float = 12.0) -> pd.DataFrame:
    """
    Return one season of player box scores, downloading if the cache is cold or
    stale. Returns None if that season has not been published.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"player_box_{year}.parquet")

    fresh = (
        os.path.exists(path)
        and (time.time() - os.path.getmtime(path)) < max_age_hours * 3600
    )
    if not fresh:
        print(f"  downloading player_box_{year}.parquet ...")
        if not _download(year, path):
            if os.path.exists(path):
                print(f"  {year} no longer published; using cached copy")
            else:
                return None
    else:
        print(f"  using cached player_box_{year}.parquet")

    return pd.read_parquet(path)


def latest_available_season(probe_from: int = None) -> int:
    """
    Find the newest published season.

    Needed because a new season's file does not exist until the season tips off.
    Probing downward means an October run does not crash looking for a file the
    upstream pipeline has not created yet.
    """
    if probe_from is None:
        # A season ending in year N tips off in October of N-1, so from October
        # onward the current calendar year + 1 may already exist.
        now = pd.Timestamp.now()
        probe_from = now.year + 1 if now.month >= 10 else now.year

    for year in range(probe_from, EARLIEST_SEASON - 1, -1):
        path = os.path.join(CACHE_DIR, f"player_box_{year}.parquet")
        if os.path.exists(path):
            return year
        try:
            req = urllib.request.Request(
                season_url(year),
                method="HEAD",
                headers={"User-Agent": "nba-pra-predictor"},
            )
            urllib.request.urlopen(req, timeout=30)
            return year
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
    raise RuntimeError("No published player_box parquet found")


def load_seasons(years) -> pd.DataFrame:
    """Concatenate several seasons, skipping any that are not published."""
    frames = []
    for y in years:
        df = load_season(y)
        if df is not None and len(df):
            frames.append(df)
    if not frames:
        raise RuntimeError(f"No data loaded for seasons {list(years)}")
    return pd.concat(frames, ignore_index=True)


# The same project also republishes data scraped from stats.nba.com itself.
# That matters: stats.nba.com blocks us directly, but its *data* is reachable
# here, which is what makes verification against the official record possible.
NBA_STATS_BASE = (
    "https://github.com/sportsdataverse/sportsdataverse-data/"
    "releases/download/nba_stats_player_season_stats"
)


def load_official_season_stats(year: int) -> pd.DataFrame:
    """
    Official NBA season totals per player, as published by stats.nba.com.

    Used only by check_parity.py, to verify our ESPN-derived box scores against
    the league's own record. Returns None if that season is not published.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"player_season_stats_{year}.parquet")

    if not os.path.exists(path):
        url = f"{NBA_STATS_BASE}/player_season_stats_{year}.parquet"
        print(f"  downloading player_season_stats_{year}.parquet ...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "nba-pra-predictor"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(path + ".tmp", "wb") as fh:
                fh.write(resp.read())
            os.replace(path + ".tmp", path)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    df = pd.read_parquet(path)
    return df[
        (df["measure_type"] == "base")
        & (df["season_type"] == "regular-season")
        & (df["per_mode"] == "totals")
    ]


NBA_SHOTS_BASE = (
    "https://github.com/sportsdataverse/sportsdataverse-data/"
    "releases/download/nba_stats_shots"
)


def load_shots(year: int) -> pd.DataFrame:
    """
    Shot-level data for one season: location, distance, and result per attempt.

    Also sourced from stats.nba.com via sportsdataverse, and -- unlike that
    project's game-log files -- refreshed daily during the season. Roughly
    4 MB per season.

    Returns None if the season is not published.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"shots_{year}.parquet")

    fresh = (
        os.path.exists(path)
        and (time.time() - os.path.getmtime(path)) < 12 * 3600
    )
    if not fresh:
        url = f"{NBA_SHOTS_BASE}/shots_{year}.parquet"
        print(f"  downloading shots_{year}.parquet ...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "nba-pra-predictor"})
            with urllib.request.urlopen(req, timeout=120) as resp, open(path + ".tmp", "wb") as fh:
                fh.write(resp.read())
            os.replace(path + ".tmp", path)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None if not os.path.exists(path) else pd.read_parquet(path)
            raise
    return pd.read_parquet(path)


def load_shots_seasons(years) -> pd.DataFrame:
    frames = [load_shots(y) for y in years]
    frames = [f for f in frames if f is not None and len(f)]
    return pd.concat(frames, ignore_index=True) if frames else None
