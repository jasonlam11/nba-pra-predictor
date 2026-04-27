from nba_api.stats.static import players
from nba_api.stats.endpoints import playergamelog, commonplayerinfo, commonteamroster
from nba_api.stats.static import teams
from nba_api.live.nba.endpoints import scoreboard as live_scoreboard
import pandas as pd
import time
import json
from datetime import datetime, timedelta

CUSTOM_HEADERS = {
    'Host': 'stats.nba.com',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/113.0',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'x-nba-stats-origin': 'stats',
    'x-nba-stats-token': 'true',
    'Connection': 'keep-alive',
    'Referer': 'https://stats.nba.com/',
    'Pragma': 'no-cache',
    'Cache-Control': 'no-cache',
}

def safe_request(func, max_retries=3, *args, **kwargs):
    """Wrapper to add delay and retries between API calls"""
    for attempt in range(max_retries):
        try:
            time.sleep(1.0)
            return func(*args, **kwargs, timeout=20, headers=CUSTOM_HEADERS)
        except Exception as e:
            print(f"Attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))  # 2s, 4s
            else:
                raise e
    return None


def get_all_active_players():
    all_players = players.get_active_players()
    print(f"Found {len(all_players)} active players")
    return all_players


def get_player_game_log(player_id: int, season: str = "2025-26"):
    try:
        game_log = safe_request(
            playergamelog.PlayerGameLog,
            player_id=player_id,
            season=season
        )
        df = game_log.get_data_frames()[0]
        return df
    except Exception as e:
        print(f"Error fetching game log for player {player_id}: {e}")
        return None


def get_player_info(player_id: int):
    try:
        info = safe_request(
            commonplayerinfo.CommonPlayerInfo,
            player_id=player_id
        )
        df = info.get_data_frames()[0]
        return df
    except Exception as e:
        print(f"Error fetching player info for {player_id}: {e}")
        return None


def search_player(name: str):
    all_players = players.get_active_players()
    if not name:
        return all_players
    return [p for p in all_players if name.lower() in p['full_name'].lower()]


def get_player_recent_stats(player_id: int, num_games: int = 5, season: str = "2025-26"):
    game_log = get_player_game_log(player_id, season)
    if game_log is None or len(game_log) == 0:
        return None

    recent_games = game_log.head(num_games)
    averages = {
        "points":      float(recent_games["PTS"].mean()),
        "rebounds":    float(recent_games["REB"].mean()),
        "assists":     float(recent_games["AST"].mean()),
        "minutes":     float(recent_games["MIN"].mean()) if "MIN" in recent_games.columns else 0,
        "games_played": len(recent_games),
    }

    games_list = []
    for _, game in recent_games.iterrows():
        games_list.append({
            "date":     game["GAME_DATE"],
            "opponent": game["MATCHUP"].split()[-1],
            "home":     "vs." in game["MATCHUP"],
            "points":   int(game["PTS"]),
            "rebounds": int(game["REB"]),
            "assists":  int(game["AST"]),
            "minutes":  int(float(game["MIN"])) if pd.notna(game["MIN"]) else 0,
            "result":   game["WL"],
        })

    return {"recent_games": games_list, "averages": averages}


def get_season_averages(player_id: int, season: str = "2025-26"):
    game_log = get_player_game_log(player_id, season)
    if game_log is None or len(game_log) == 0:
        return None

    return {
        "points":      float(game_log["PTS"].mean()),
        "rebounds":    float(game_log["REB"].mean()),
        "assists":     float(game_log["AST"].mean()),
        "minutes":     float(game_log["MIN"].mean()) if "MIN" in game_log.columns else 0,
        "games_played": len(game_log),
        "fg_pct":      float(game_log["FG_PCT"].mean()),
        "fg3_pct":     float(game_log["FG3_PCT"].mean()),
        "ft_pct":      float(game_log["FT_PCT"].mean()),
    }


def get_todays_games_structured():
    try:
        board = live_scoreboard.ScoreBoard()
        games_data = board.games.get_dict()
        print(f"Live scoreboard: {len(games_data)} games today")

        games = []
        for g in games_data:
            home = g["homeTeam"]
            away = g["awayTeam"]
            games.append({
                "game_id":   g["gameId"],
                "status":    g.get("gameStatusText", ""),
                "home_team": {
                    "id":           home["teamId"],
                    "name":         home["teamName"],
                    "city":         home["teamCity"],
                    "abbreviation": home["teamTricode"],
                    "record":       f"{home.get('wins', 0)}-{home.get('losses', 0)}",
                },
                "away_team": {
                    "id":           away["teamId"],
                    "name":         away["teamName"],
                    "city":         away["teamCity"],
                    "abbreviation": away["teamTricode"],
                    "record":       f"{away.get('wins', 0)}-{away.get('losses', 0)}",
                },
            })

        return games

    except Exception as e:
        import traceback
        print(f"Error fetching today's games: {e}")
        traceback.print_exc()
        return []


def get_team_roster(team_id: int, season: str = "2025-26"):
    try:
        roster = safe_request(
            commonteamroster.CommonTeamRoster,
            team_id=team_id,
            season=season,
        )
        df = roster.get_data_frames()[0]

        result = []
        for _, row in df.iterrows():
            result.append({
                "id":       int(row["PLAYER_ID"]),
                "name":     row["PLAYER"],
                "number":   str(row.get("NUM", "")),
                "position": str(row.get("POSITION", "")),
            })
        return result

    except Exception as e:
        print(f"Error fetching roster for team {team_id}: {e}")
        return []
