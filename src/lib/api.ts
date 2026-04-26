const API_BASE = "http://localhost:8000";

export interface Player {
    id: number;
    full_name: string;
    first_name: string;
    last_name: string;
    is_active: boolean;
}

export interface GameLog {
    date: string;
    opponent: string;
    home: boolean;
    points: number;
    rebounds: number;
    assists: number;
    minutes: number;
    result: string;
}

export interface Prediction {
    points: number;
    rebounds: number;
    assists: number;
    total_pra: number;
    confidence: number;
}

export interface PlayerStats {
    player: Player;
    prediction: Prediction;
    recent_games: GameLog[];
    last_5_avg: {
        points: number;
        rebounds: number;
        assists: number;
        minutes: number;
        games_played: number;
    };
    season_avg: {
        points: number;
        rebounds: number;
        assists: number;
        minutes: number;
        games_played: number;
    };
}

export async function searchPlayers(query: string): Promise<Player[]> {
    if (query.length < 2) return [];

    try {
        const res = await fetch(`${API_BASE}/players/search?q=${encodeURIComponent(query)}`);
        if (!res.ok) throw new Error("Failed to search players");
        return res.json();
    } catch (error) {
        console.error("Search error:", error);
        return [];
    }
}

export async function getPlayerStats(playerId: number): Promise<PlayerStats | null> {
    try {
        const res = await fetch(`${API_BASE}/players/${playerId}/stats`);
        if (!res.ok) throw new Error("Failed to get player stats");
        return res.json();
    } catch (error) {
        console.error("Stats error:", error);
        return null;
    }
}