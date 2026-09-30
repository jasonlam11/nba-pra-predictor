const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type StatType = "pra" | "pts" | "reb" | "ast";

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

export interface Reason {
    text: string;
    positive: boolean; // true = pushes stat UP, false = pushes stat DOWN
}

export interface StatReasons {
    pra: Reason[];
    pts: Reason[];
    reb: Reason[];
    ast: Reason[];
}

export interface InjuryInfo {
    status: string;       // "Out" | "Questionable" | "Day-To-Day" | "Doubtful" | "Probable" | ...
    description: string;  // injury type e.g. "Knee", "Ankle"
}

export interface TeamDefense {
    pts_allowed: number;
    pts_rank: number;
    reb_allowed: number;
    reb_rank: number;
    ast_allowed: number;
    ast_rank: number;
    overall_rank: number;
}

export interface AbsentTeammate {
    name: string;
    status: string;   // "Out" | "Doubtful"
    minutes: number;  // recent minutes per game, i.e. the usage now up for grabs
}

export interface PlayerStats {
    player: Player;
    prediction: Prediction;
    /** Rotation teammates ruled out — their minutes tend to redistribute. */
    absent_teammates?: AbsentTeammate[];
    absent_minutes?: number;
    recent_games: GameLog[];
    last_20_games: GameLog[];
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
    reasons: StatReasons;
}

export interface TeamInfo {
    id: number;
    name: string;
    city: string;
    abbreviation: string;
    record: string;
}

export interface Game {
    game_id: string;
    status: string;
    home_team: TeamInfo;
    away_team: TeamInfo;
}

export interface RosterPlayer {
    id: number;
    name: string;
    number: string;
    position: string;
}

export async function getInjuries(): Promise<Record<string, InjuryInfo>> {
    try {
        const res = await fetch(`${API_BASE}/injuries`);
        if (!res.ok) return {};
        return res.json();
    } catch {
        return {};
    }
}

export async function getDefenseRatings(): Promise<Record<string, TeamDefense>> {
    try {
        const res = await fetch(`${API_BASE}/teams/defense-ratings`);
        if (!res.ok) return {};
        return res.json();
    } catch {
        return {};
    }
}

export async function getTodaysGames(): Promise<Game[]> {
    try {
        const res = await fetch(`${API_BASE}/games/today`);
        if (!res.ok) throw new Error("Failed to fetch games");
        return res.json();
    } catch (error) {
        console.error("Games error:", error);
        return [];
    }
}

export async function getTeamRoster(teamId: number): Promise<RosterPlayer[]> {
    try {
        const res = await fetch(`${API_BASE}/teams/${teamId}/players`);
        if (!res.ok) throw new Error("Failed to fetch roster");
        return res.json();
    } catch (error) {
        console.error("Roster error:", error);
        return [];
    }
}

export async function searchPlayers(query: string): Promise<Player[]> {
    // Trim, cap length, strip anything that isn't a letter/space/hyphen/apostrophe/dot
    const sanitized = query.trim().slice(0, 50).replace(/[^a-zA-Z\s'\-.]/g, "");
    if (sanitized.length < 2) return [];

    try {
        const res = await fetch(`${API_BASE}/players/search?q=${encodeURIComponent(sanitized)}`);
        if (!res.ok) throw new Error("Failed to search players");
        return res.json();
    } catch (error) {
        console.error("Search error:", error);
        return [];
    }
}

export async function getPlayerStats(playerId: number): Promise<{ data: PlayerStats | null; error: string | null }> {
    try {
        const res = await fetch(`${API_BASE}/players/${playerId}/stats`);
        if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            const msg = body?.detail ?? "Failed to load player stats.";
            return { data: null, error: msg };
        }
        const data = await res.json();
        return { data, error: null };
    } catch (error) {
        console.error("Stats error:", error);
        return { data: null, error: "Could not reach the server. Make sure the backend is running." };
    }
}
export interface SnapshotHealth {
    status: string;
    snapshot_loaded: boolean;
    snapshot_built_at: string | null;
    snapshot_age_hours: number | null;
    stale: boolean;
    n_players: number;
    n_predictions: number;
    data_through: string | null;
    model_trained_at: string | null;
    source_years: string | null;
}

/**
 * Freshness of the data the API is serving.
 *
 * Predictions come from a snapshot rebuilt once a day, not from a live feed,
 * so the UI has to say when the data is from rather than imply it is current.
 */
export async function getHealth(): Promise<SnapshotHealth | null> {
    try {
        const res = await fetch(`${API_BASE}/health`);
        if (!res.ok) return null;
        return res.json();
    } catch (error) {
        console.error("Health error:", error);
        return null;
    }
}
