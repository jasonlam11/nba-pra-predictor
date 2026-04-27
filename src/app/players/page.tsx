"use client";

import { useState } from "react";
import PRACard from "@/components/PRACard";
import StatCard from "@/components/StatCard";
import PropLineAnalyzer from "@/components/PropLineAnalyzer";
import GameHistoryChart from "@/components/LastFiveChart";
import { Player, PlayerStats, StatType, searchPlayers, getPlayerStats } from "@/lib/api";
import { usePinnedPlayers } from "@/lib/usePinnedPlayers";

export default function PlayersPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Player[]>([]);
  const [searching, setSearching] = useState(false);

  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(null);
  const [selectedPlayerName, setSelectedPlayerName] = useState<string | null>(null);
  const [playerStats, setPlayerStats] = useState<PlayerStats | null>(null);
  const [playerLoading, setPlayerLoading] = useState(false);
  const [playerError, setPlayerError] = useState<string | null>(null);

  const [selectedStat, setSelectedStat] = useState<StatType>("pra");
  const [propLine, setPropLine] = useState<number>(0);

  const { isPinned, togglePin } = usePinnedPlayers();

  let debounceTimer: ReturnType<typeof setTimeout>;

  const handleQueryChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setQuery(val);
    clearTimeout(debounceTimer);
    if (val.length < 2) {
      setResults([]);
      return;
    }
    debounceTimer = setTimeout(async () => {
      setSearching(true);
      const data = await searchPlayers(val);
      setResults(data.slice(0, 20));
      setSearching(false);
    }, 300);
  };

  const handleSelectPlayer = async (player: Player) => {
    setSelectedPlayerId(player.id);
    setSelectedPlayerName(player.full_name);
    setResults([]);
    setQuery(player.full_name);
    setPlayerLoading(true);
    setPlayerError(null);
    setPlayerStats(null);

    const { data: stats, error } = await getPlayerStats(player.id);
    if (stats) {
      setPlayerStats(stats);
      setSelectedStat("pra");
      setPropLine(Math.round(stats.prediction.total_pra * 2) / 2);
    } else {
      setPlayerError(error ?? "Failed to load player stats.");
    }
    setPlayerLoading(false);
  };

  const handleClear = () => {
    setQuery("");
    setResults([]);
    setSelectedPlayerId(null);
    setSelectedPlayerName(null);
    setPlayerStats(null);
    setPlayerError(null);
  };

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
      {/* Search bar */}
      <section className="mb-8">
        <h2 className="font-display text-3xl text-chalk mb-4">Players</h2>
        <div className="relative max-w-lg">
          <svg
            className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-dust pointer-events-none"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            value={query}
            onChange={handleQueryChange}
            placeholder="Search any active NBA player..."
            className="w-full bg-hardwood border border-sideline rounded-xl pl-11 pr-10 py-3 text-chalk placeholder-dust/50 focus:outline-none focus:border-gold/60 transition-colors"
            autoFocus
          />
          {query && (
            <button
              onClick={handleClear}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-dust hover:text-chalk transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>

        {/* Search results dropdown */}
        {results.length > 0 && (
          <div className="mt-2 max-w-lg bg-hardwood border border-sideline rounded-xl overflow-hidden shadow-lg">
            {results.map((player) => (
              <button
                key={player.id}
                onClick={() => handleSelectPlayer(player)}
                className="w-full text-left px-4 py-3 text-chalk hover:bg-sideline transition-colors border-b border-sideline/50 last:border-0 text-sm flex items-center justify-between group"
              >
                <span>{player.full_name}</span>
                <svg
                  className="w-4 h-4 text-dust group-hover:text-gold transition-colors"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </button>
            ))}
          </div>
        )}

        {searching && (
          <div className="mt-3 flex items-center gap-2 text-dust text-sm">
            <div className="w-3.5 h-3.5 border-2 border-gold border-t-transparent rounded-full animate-spin" />
            Searching...
          </div>
        )}
      </section>

      {/* Player detail */}
      {selectedPlayerName && (
        <div className="animate-fade-in">
          {/* Player header */}
          <section className="mb-8 flex items-center gap-4">
            <h2 className="font-display text-4xl text-chalk">{selectedPlayerName}</h2>
            {selectedPlayerId && (
              <button
                onClick={() => togglePin(selectedPlayerId, selectedPlayerName)}
                title={isPinned(selectedPlayerId) ? "Unpin player" : "Pin player"}
                className="flex-shrink-0 transition-transform hover:scale-110 active:scale-95"
              >
                {isPinned(selectedPlayerId) ? (
                  <svg className="w-7 h-7 text-gold" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                  </svg>
                ) : (
                  <svg className="w-7 h-7 text-dust hover:text-gold transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                  </svg>
                )}
              </button>
            )}
          </section>

          {/* Loading */}
          {playerLoading && (
            <div className="text-center py-20">
              <div className="w-16 h-16 border-4 border-gold border-t-transparent rounded-full animate-spin mx-auto mb-4" />
              <p className="text-dust">Loading stats...</p>
            </div>
          )}

          {/* Error */}
          {playerError && !playerLoading && (
            <div className="text-center py-20">
              <div className="w-20 h-20 bg-hardwood rounded-full flex items-center justify-center mx-auto mb-6">
                <svg className="w-10 h-10 text-highlight" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>
              <h3 className="font-display text-2xl text-dust mb-2">Error Loading Stats</h3>
              <p className="text-dust/70 max-w-md mx-auto">{playerError}</p>
            </div>
          )}

          {/* Stats */}
          {playerStats && !playerLoading && (
            <>
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2 space-y-6">
                  <PRACard
                    points={playerStats.prediction.points}
                    rebounds={playerStats.prediction.rebounds}
                    assists={playerStats.prediction.assists}
                    opponent="—"
                    gameTime="Season Projection"
                    isHome={true}
                    confidence={playerStats.prediction.confidence}
                  />
                  <PropLineAnalyzer
                    prediction={playerStats.prediction}
                    last20Games={playerStats.last_20_games}
                    reasons={playerStats.reasons}
                    selectedStat={selectedStat}
                    onStatChange={setSelectedStat}
                    line={propLine}
                    onLineChange={setPropLine}
                  />
                </div>
                <div className="space-y-4">
                  <h3 className="font-display text-xl text-dust uppercase tracking-widest">Season Averages</h3>
                  <StatCard label="Points"   value={playerStats.season_avg.points}   color="gold"      size="sm" />
                  <StatCard label="Rebounds" value={playerStats.season_avg.rebounds} color="ice"       size="sm" />
                  <StatCard label="Assists"  value={playerStats.season_avg.assists}  color="highlight" size="sm" />
                </div>
              </div>

              <section className="mt-8">
                <GameHistoryChart
                  games={playerStats.last_20_games}
                  selectedStat={selectedStat}
                  propLine={propLine}
                />
              </section>
            </>
          )}
        </div>
      )}

      {/* Empty state */}
      {!selectedPlayerName && !searching && query.length < 2 && (
        <div className="text-center py-24">
          <div className="w-20 h-20 bg-hardwood rounded-full flex items-center justify-center mx-auto mb-6">
            <svg className="w-10 h-10 text-dust" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </div>
          <h3 className="font-display text-2xl text-dust mb-2">Search Any Player</h3>
          <p className="text-dust/70">Type a name above to look up stats and projections for any active NBA player.</p>
        </div>
      )}
    </main>
  );
}
