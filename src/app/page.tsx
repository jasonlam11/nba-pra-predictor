"use client";

import { useState, useEffect } from "react";
import PlayerSearch from "@/components/PlayerSearch";
import PRACard from "@/components/PRACard";
import StatCard from "@/components/StatCard";
import GameCard from "@/components/GameCard";
import PropLineAnalyzer from "@/components/PropLineAnalyzer";
import GameHistoryChart from "@/components/LastFiveChart";
import PinnedPlayers from "@/components/PinnedPlayers";
import { Player, PlayerStats, Game, StatType, TeamDefense, InjuryInfo, getPlayerStats, getTodaysGames, getInjuries, getDefenseRatings } from "@/lib/api";
import { usePinnedPlayers } from "@/lib/usePinnedPlayers";

export default function Home() {
  // --- Games state ---
  const [games, setGames] = useState<Game[]>([]);
  const [gamesLoading, setGamesLoading] = useState(true);
  const [injuries, setInjuries] = useState<Record<string, InjuryInfo>>({});
  const [defenseRatings, setDefenseRatings] = useState<Record<string, TeamDefense>>({});

  // --- Player state ---
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(null);
  const [selectedPlayerName, setSelectedPlayerName] = useState<string | null>(null);
  const [gameContext, setGameContext] = useState<{ opponent: string; isHome: boolean } | null>(null);
  const [playerStats, setPlayerStats] = useState<PlayerStats | null>(null);
  const [playerLoading, setPlayerLoading] = useState(false);
  const [playerError, setPlayerError] = useState<string | null>(null);

  // --- Shared prop analyzer + chart state ---
  const [selectedStat, setSelectedStat] = useState<StatType>("pra");
  const [propLine, setPropLine] = useState<number>(0);

  // --- Pinned players ---
  const { pinned, isPinned, togglePin, ready: pinsReady } = usePinnedPlayers();

  // Load today's games, injuries, and defense ratings on mount
  useEffect(() => {
    getTodaysGames().then((data) => {
      setGames(data);
      setGamesLoading(false);
    }).catch(() => {
      setGamesLoading(false);
    });
    getInjuries().then(setInjuries).catch(() => {});
    getDefenseRatings().then(setDefenseRatings).catch(() => {});
  }, []);

  const loadPlayerStats = async (playerId: number) => {
    setPlayerLoading(true);
    setPlayerError(null);
    setPlayerStats(null);

    const { data: stats, error } = await getPlayerStats(playerId);
    if (stats) {
      setPlayerStats(stats);
      setSelectedStat("pra");
      setPropLine(Math.round(stats.prediction.total_pra * 2) / 2);
    } else {
      setPlayerError(error ?? "Failed to load player stats.");
    }
    setPlayerLoading(false);
  };

  const handleSelectPlayer = (playerId: number, playerName: string, opponent?: string, isHome?: boolean) => {
    setSelectedPlayerId(playerId);
    setSelectedPlayerName(playerName);
    setGameContext(opponent != null && isHome != null ? { opponent, isHome } : null);
    loadPlayerStats(playerId);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleSelectPlayerFromSearch = (player: Player) => {
    handleSelectPlayer(player.id, player.full_name);
  };

  const handleBack = () => {
    setSelectedPlayerId(null);
    setSelectedPlayerName(null);
    setGameContext(null);
    setPlayerStats(null);
    setPlayerError(null);
  };

  const showingPlayer = selectedPlayerName !== null;

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 py-6 sm:py-8">

      {/* ── Player detail view ── */}
      {showingPlayer && (
        <div className="animate-fade-in">
          {/* Back button */}
          <button
            onClick={handleBack}
            className="flex items-center gap-2 text-dust hover:text-chalk transition-colors mb-8 group"
          >
            <svg className="w-4 h-4 group-hover:-translate-x-0.5 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            <span className="text-sm">Back to Today&apos;s Games</span>
          </button>

          {/* Player header with pin button */}
          <section className="mb-8 flex items-center gap-4">
            <h2 className="font-display text-4xl text-chalk">{selectedPlayerName}</h2>
            {selectedPlayerId && selectedPlayerName && (
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
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 sm:gap-6">
                <div className="lg:col-span-2 space-y-6">
                  <PRACard
                    points={playerStats.prediction.points}
                    rebounds={playerStats.prediction.rebounds}
                    assists={playerStats.prediction.assists}
                    opponent={gameContext?.opponent ?? "—"}
                    gameTime={gameContext ? "Today" : "Season Projection"}
                    isHome={gameContext?.isHome ?? true}
                    confidence={playerStats.prediction.confidence}
                    defense={gameContext?.opponent ? (defenseRatings[gameContext.opponent] ?? null) : null}
                    injuryStatus={selectedPlayerName ? (injuries[selectedPlayerName.toLowerCase()] ?? null) : null}
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

      {/* ── Today's Games view (default) ── */}
      {!showingPlayer && (
        <>
          {/* Search */}
          <section className="mb-10">
            <h2 className="font-display text-3xl text-chalk mb-4">Find a Player</h2>
            <PlayerSearch onSelectPlayer={handleSelectPlayerFromSearch} />
          </section>

          {/* Pinned players */}
          {pinsReady && (
            <PinnedPlayers
              players={pinned}
              onSelect={(id, name) => handleSelectPlayer(id, name)}
              onUnpin={(id, name) => togglePin(id, name)}
            />
          )}

          {/* Games section */}
          <section>
            <div className="flex items-center justify-between mb-6">
              <h2 className="font-display text-3xl text-chalk">Today&apos;s Games</h2>
              <span className="text-dust text-sm font-mono" suppressHydrationWarning>
                {new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
              </span>
            </div>

            {gamesLoading && (
              <div className="flex items-center justify-center py-20 gap-3">
                <div className="w-6 h-6 border-2 border-gold border-t-transparent rounded-full animate-spin" />
                <span className="text-dust">Loading today&apos;s games...</span>
              </div>
            )}

            {!gamesLoading && games.length === 0 && (
              <div className="text-center py-20">
                <div className="w-20 h-20 bg-hardwood rounded-full flex items-center justify-center mx-auto mb-6">
                  <svg className="w-10 h-10 text-dust" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                </div>
                <h3 className="font-display text-2xl text-dust mb-2">No Games Today</h3>
                <p className="text-dust/70">Use the search above to look up any player.</p>
              </div>
            )}

            {!gamesLoading && games.length > 0 && (
              <div className="space-y-3">
                {games.map((game) => (
                  <GameCard
                    key={game.game_id}
                    game={game}
                    injuries={injuries}
                    onSelectPlayer={(id, name, opp, home) => handleSelectPlayer(id, name, opp, home)}
                  />
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </main>
  );
}
