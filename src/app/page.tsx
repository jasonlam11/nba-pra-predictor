"use client";

import { useState } from "react";
import PlayerSearch from "@/components/PlayerSearch";
import PRACard from "@/components/PRACard";
import StatCard from "@/components/StatCard";
import LastFiveChart from "@/components/LastFiveChart";
import { Player, PlayerStats, getPlayerStats } from "@/lib/api";

export default function Home() {
  const [selectedPlayer, setSelectedPlayer] = useState<Player | null>(null);
  const [playerStats, setPlayerStats] = useState<PlayerStats | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSelectPlayer = async (player: Player) => {
    setSelectedPlayer(player);
    setIsLoading(true);
    setError(null);

    const stats = await getPlayerStats(player.id);

    if (stats) {
      setPlayerStats(stats);
    } else {
      setError("Failed to load player stats. The NBA API may be rate-limited. Try again in a moment.");
    }

    setIsLoading(false);
  };

  return (
    <main className="max-w-7xl mx-auto px-6 py-8">
      {/* Search Section */}
      <section className="mb-12">
        <h2 className="font-display text-3xl text-chalk mb-4">Select a Player</h2>
        <PlayerSearch onSelectPlayer={handleSelectPlayer} />
      </section>

      {/* Loading State */}
      {isLoading && (
        <div className="text-center py-20">
          <div className="w-16 h-16 border-4 border-gold border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-dust">Loading player stats...</p>
        </div>
      )}

      {/* Error State */}
      {error && !isLoading && (
        <div className="text-center py-20">
          <div className="w-20 h-20 bg-hardwood rounded-full flex items-center justify-center mx-auto mb-6">
            <svg className="w-10 h-10 text-highlight" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <h3 className="font-display text-2xl text-dust mb-2">Error Loading Stats</h3>
          <p className="text-dust/70 max-w-md mx-auto">{error}</p>
        </div>
      )}

      {/* Player Stats */}
      {selectedPlayer && playerStats && !isLoading && (
        <div className="animate-fade-in">
          {/* Player Header */}
          <section className="mb-8">
            <h2 className="font-display text-4xl text-chalk">{selectedPlayer.full_name}</h2>
          </section>

          {/* Main Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Prediction Card */}
            <div className="lg:col-span-2">
              <PRACard
                points={playerStats.prediction.points}
                rebounds={playerStats.prediction.rebounds}
                assists={playerStats.prediction.assists}
                opponent="Next Game"
                gameTime="Check Schedule"
                isHome={true}
                confidence={playerStats.prediction.confidence}
              />
            </div>

            {/* Season Averages */}
            <div className="space-y-4">
              <h3 className="font-display text-xl text-dust uppercase tracking-widest">
                Season Averages
              </h3>
              <StatCard label="Points" value={playerStats.season_avg.points} color="gold" size="sm" />
              <StatCard label="Rebounds" value={playerStats.season_avg.rebounds} color="ice" size="sm" />
              <StatCard label="Assists" value={playerStats.season_avg.assists} color="highlight" size="sm" />
            </div>
          </div>

          {/* Last 5 Games Chart */}
          <section className="mt-12">
            <LastFiveChart games={playerStats.recent_games} />
          </section>

          {/* Last 5 Games Average */}
          <section className="mt-12">
            <h3 className="font-display text-2xl text-chalk mb-6">Last 5 Games Average</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <StatCard label="Points" value={playerStats.last_5_avg.points} color="gold" />
              <StatCard label="Rebounds" value={playerStats.last_5_avg.rebounds} color="ice" />
              <StatCard label="Assists" value={playerStats.last_5_avg.assists} color="highlight" />
            </div>
          </section>
        </div>
      )}

      {/* Empty State */}
      {!selectedPlayer && !isLoading && (
        <div className="text-center py-20">
          <div className="w-20 h-20 bg-hardwood rounded-full flex items-center justify-center mx-auto mb-6">
            <svg className="w-10 h-10 text-dust" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
            </svg>
          </div>
          <h3 className="font-display text-2xl text-dust mb-2">No Player Selected</h3>
          <p className="text-dust/70">Search for a player above to see their predicted stats</p>
        </div>
      )}
    </main>
  );
}