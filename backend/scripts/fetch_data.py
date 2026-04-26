from nba_api.stats.static import players
from nba_api.stats.endpoints import playergamelog, commonplayerinfo, scoreboardv2
from nba_api.stats.static import teams
import pandas as pd
import time
import json
from datetime import datetime, timedelta

# Custom headers to avoid blocks
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
            time.sleep(1.0)  # 1 second delay
            return func(*args, **kwargs, timeout=60, headers=CUSTOM_HEADERS)
        except Exception as e:
            print(f"Attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(3)  # Wait longer before retry
            else:
                raise e
    return None


def get_all_active_players():
    """Get list of all active NBA players"""
    all_players = players.get_active_players()
    print(f"Found {len(all_players)} active players")
    return all_players


def get_player_game_log(player_id: int, season: str = "2025-26"):
    """
    Get game log for a specific player
    """
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
    """Get detailed player info"""
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


def get_todays_games():
    """Get today's NBA games"""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        scoreboard = safe_request(
            scoreboardv2.ScoreboardV2,
            game_date=today
        )
        games = scoreboard.get_data_frames()[0]
        return games
    except Exception as e:
        print(f"Error fetching today's games: {e}")
        return None


def search_player(name: str):
    """Search for a player by name"""
    all_players = players.get_active_players()
    if not name:
        return all_players
    matches = [p for p in all_players if name.lower() in p['full_name'].lower()]
    return matches


def get_player_recent_stats(player_id: int, num_games: int = 5, season: str = "2025-26"):
    """
    Get a player's recent game stats
    """
    game_log = get_player_game_log(player_id, season)
    
    if game_log is None or len(game_log) == 0:
        return None
    
    # Get last N games
    recent_games = game_log.head(num_games)
    
    # Calculate averages
    averages = {
        "points": float(recent_games["PTS"].mean()),
        "rebounds": float(recent_games["REB"].mean()),
        "assists": float(recent_games["AST"].mean()),
        "minutes": float(recent_games["MIN"].mean()) if "MIN" in recent_games.columns else 0,
        "games_played": len(recent_games)
    }
    
    # Format game log
    games_list = []
    for _, game in recent_games.iterrows():
        games_list.append({
            "date": game["GAME_DATE"],
            "opponent": game["MATCHUP"].split()[-1],
            "home": "vs." in game["MATCHUP"],
            "points": int(game["PTS"]),
            "rebounds": int(game["REB"]),
            "assists": int(game["AST"]),
            "minutes": int(float(game["MIN"])) if pd.notna(game["MIN"]) else 0,
            "result": game["WL"]
        })
    
    return {
        "recent_games": games_list,
        "averages": averages
    }


def get_season_averages(player_id: int, season: str = "2025-26"):
    """Get player's season averages"""
    game_log = get_player_game_log(player_id, season)
    
    if game_log is None or len(game_log) == 0:
        return None
    
    return {
        "points": float(game_log["PTS"].mean()),
        "rebounds": float(game_log["REB"].mean()),
        "assists": float(game_log["AST"].mean()),
        "minutes": float(game_log["MIN"].mean()) if "MIN" in game_log.columns else 0,
        "games_played": len(game_log),
        "fg_pct": float(game_log["FG_PCT"].mean()),
        "fg3_pct": float(game_log["FG3_PCT"].mean()),
        "ft_pct": float(game_log["FT_PCT"].mean())
    }


# ============ TEST THE SCRIPT ============
if __name__ == "__main__":
    print("=" * 50)
    print("NBA Data Fetcher - Test Run")
    print("=" * 50)
    
    print("\n1. Searching for 'LeBron'...")
    results = search_player("LeBron")
    if results:
        player = results[0]
        print(f"   Found: {player['full_name']} (ID: {player['id']})")
        
        print(f"\n2. Fetching recent stats for {player['full_name']}...")
        recent = get_player_recent_stats(player['id'])
        
        if recent:
            print(f"\n   Last 5 Games Averages:")
            print(f"   - Points:   {recent['averages']['points']:.1f}")
            print(f"   - Rebounds: {recent['averages']['rebounds']:.1f}")
            print(f"   - Assists:  {recent['averages']['assists']:.1f}")
            
            print(f"\n   Recent Games:")
            for game in recent['recent_games']:
                pra = game['points'] + game['rebounds'] + game['assists']
                print(f"   - {game['date']}: vs {game['opponent']} | {game['points']}/{game['rebounds']}/{game['assists']} ({pra} PRA) | {game['result']}")
        
        print(f"\n3. Fetching season averages...")
        season = get_season_averages(player['id'])
        
        if season:
            print(f"\n   Season Averages ({season['games_played']} games):")
            print(f"   - Points:   {season['points']:.1f}")
            print(f"   - Rebounds: {season['rebounds']:.1f}")
            print(f"   - Assists:  {season['assists']:.1f}")
    
    print("\n" + "=" * 50)
    print("Test complete!")
    print("=" * 50)