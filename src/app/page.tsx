"use client";

import { useState } from "react";
import PlayerSearch from "@/components/PlayerSearch";
import PRACard from "@/components/PRACard";
import StatCard from "@/components/StatCard";

interface Player {
  id: number;
  name: string;
  team: string;
  position: string;
}

// Mock prediction data
const MOCK_PREDICTION = {
  points: 28.4,
  rebounds: 8.2,
  assists: 6.1,
  opponent: "Lakers",
  gameTime: "Tomorrow 7:30 PM",
  isHome: true,
  confidence: 82,
};

// Mock last 5 games
const MOCK_LAST_5 = {
  points: 27.2,
  rebounds: 7.8,
  assists: 6.4,
};

// Mock season averages
const MOCK_SEASON = {
  points: 25.8,
  rebounds: 7.2,
  assists: 5.9,
};

export default function Home() {
  const [selectedPlayer, setSelectedPlayer] = useState<Player | null>(null);

  return (
    <main className="max-w-7xl mx-auto px-6 py-8">
      {/* Search Section */}
      <section className="mb-12">
        <h2 className="font-display text-3xl text-chalk mb-4">
          Select a Player
        </h2>
        <PlayerSearch onSelectPlayer={setSelectedPlayer} />
      </section>

      {/* Show prediction if player selected */}
      {selectedPlayer ? (
        <div className="animate-fade-in">
          {/* Player Header */}
          <section className="mb-8">
            <h2 className="font-display text-4xl text-chalk">
              {selectedPlayer.name}
            </h2>
            <p className="text-dust mt-1">
              {selectedPlayer.team} • {selectedPlayer.position}
            </p>
          </section>

          {/* Main Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Prediction Card - Takes 2 columns on large screens */}
            <div className="lg:col-span-2">
              <PRACard {...MOCK_PREDICTION} />
            </div>

            {/* Season Averages */}
            <div className="space-y-4">
              <h3 className="font-display text-xl text-dust uppercase tracking-widest">
                Season Averages
              </h3>
              <StatCard label="Points" value={MOCK_SEASON.points} color="gold" size="sm" />
              <StatCard label="Rebounds" value={MOCK_SEASON.rebounds} color="ice" size="sm" />
              <StatCard label="Assists" value={MOCK_SEASON.assists} color="highlight" size="sm" />
            </div>
          </div>

          {/* Last 5 Games Section */}
          <section className="mt-12">
            <h3 className="font-display text-2xl text-chalk mb-6">
              Last 5 Games Average
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <StatCard label="Points" value={MOCK_LAST_5.points} color="gold" />
              <StatCard label="Rebounds" value={MOCK_LAST_5.rebounds} color="ice" />
              <StatCard label="Assists" value={MOCK_LAST_5.assists} color="highlight" />
            </div>
          </section>
        </div>
      ) : (
        /* Empty State */
        <div className="text-center py-20">
          <div className="w-20 h-20 bg-hardwood rounded-full flex items-center justify-center mx-auto mb-6">
            <svg className="w-10 h-10 text-dust" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
            </svg>
          </div>
          <h3 className="font-display text-2xl text-dust mb-2">
            No Player Selected
          </h3>
          <p className="text-dust/70">
            Search for a player above to see their predicted stats
          </p>
        </div>
      )}
    </main>
  );
}