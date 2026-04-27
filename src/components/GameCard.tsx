"use client";

import { Game, RosterPlayer, InjuryInfo, getTeamRoster } from "@/lib/api";
import { useState } from "react";

interface GameCardProps {
  game: Game;
  injuries?: Record<string, InjuryInfo>;
  onSelectPlayer: (playerId: number, playerName: string, opponent: string, isHome: boolean) => void;
}

function injuryBadge(name: string, injuries?: Record<string, InjuryInfo>) {
  if (!injuries) return null;
  const info = injuries[name.toLowerCase()];
  if (!info) return null;

  const s = info.status.toLowerCase();
  const isOut      = s === "out" || s === "doubtful" || s.includes("season") || s.includes("reserve");
  const isQTD      = s === "questionable" || s === "day-to-day" || s === "gtd";

  const cls = isOut
    ? "bg-highlight/20 text-highlight border-highlight/40"
    : isQTD
    ? "bg-gold/20 text-gold border-gold/40"
    : "bg-green-500/10 text-green-400 border-green-500/30";

  const label = isOut ? "OUT" : isQTD ? info.status.toUpperCase() : "PROB";

  return (
    <span className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded border ${cls}`} title={info.description}>
      {label}
    </span>
  );
}

export default function GameCard({ game, injuries, onSelectPlayer }: GameCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [homeRoster, setHomeRoster] = useState<RosterPlayer[] | null>(null);
  const [awayRoster, setAwayRoster] = useState<RosterPlayer[] | null>(null);
  const [loadingRoster, setLoadingRoster] = useState(false);

  const handleExpand = async () => {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (homeRoster !== null) return; // already fetched

    setLoadingRoster(true);
    const [home, away] = await Promise.all([
      getTeamRoster(game.home_team.id),
      getTeamRoster(game.away_team.id),
    ]);
    setHomeRoster(home);
    setAwayRoster(away);
    setLoadingRoster(false);
  };

  const isLive = game.status.includes("QTR") || game.status.includes("Half") || game.status.includes("OT");
  const isFinal = game.status.toLowerCase().includes("final");

  return (
    <div className="bg-hardwood border border-sideline rounded-xl overflow-hidden transition-all duration-200">
      {/* Game header row */}
      <button
        onClick={handleExpand}
        className="w-full px-6 py-5 flex items-center justify-between hover:bg-sideline/30 transition-colors"
      >
        {/* Away team */}
        <div className="flex items-center gap-3 w-2/5">
          <span className="font-display text-2xl text-chalk">{game.away_team.abbreviation}</span>
          <div className="text-left hidden sm:block">
            <p className="text-chalk/80 text-sm font-medium">{game.away_team.city}</p>
            <p className="text-dust text-xs">{game.away_team.record}</p>
          </div>
        </div>

        {/* Status / score */}
        <div className="text-center flex-1">
          {isLive ? (
            <span className="inline-flex items-center gap-1.5 px-3 py-1 bg-highlight/20 border border-highlight/40 rounded-full">
              <span className="w-1.5 h-1.5 bg-highlight rounded-full animate-pulse" />
              <span className="text-highlight text-xs font-mono font-bold">{game.status}</span>
            </span>
          ) : isFinal ? (
            <span className="text-dust text-sm font-mono">FINAL</span>
          ) : (
            <span className="text-gold text-sm font-mono">{game.status}</span>
          )}
        </div>

        {/* Home team */}
        <div className="flex items-center gap-3 w-2/5 justify-end">
          <div className="text-right hidden sm:block">
            <p className="text-chalk/80 text-sm font-medium">{game.home_team.city}</p>
            <p className="text-dust text-xs">{game.home_team.record}</p>
          </div>
          <span className="font-display text-2xl text-chalk">{game.home_team.abbreviation}</span>
        </div>

        {/* Chevron */}
        <svg
          className={`w-4 h-4 text-dust ml-4 flex-shrink-0 transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Roster panel */}
      {expanded && (
        <div className="border-t border-sideline px-6 py-5 animate-fade-in">
          {loadingRoster ? (
            <div className="flex items-center justify-center py-8 gap-3">
              <div className="w-5 h-5 border-2 border-gold border-t-transparent rounded-full animate-spin" />
              <span className="text-dust text-sm">Loading rosters...</span>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              {/* Away roster */}
              <RosterColumn
                team={game.away_team}
                opponent={game.home_team.abbreviation}
                isHome={false}
                players={awayRoster ?? []}
                injuries={injuries}
                onSelectPlayer={onSelectPlayer}
              />
              {/* Home roster */}
              <RosterColumn
                team={game.home_team}
                opponent={game.away_team.abbreviation}
                isHome={true}
                players={homeRoster ?? []}
                injuries={injuries}
                onSelectPlayer={onSelectPlayer}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RosterColumn({
  team,
  opponent,
  isHome,
  players,
  injuries,
  onSelectPlayer,
}: {
  team: Game["home_team"];
  opponent: string;
  isHome: boolean;
  players: RosterPlayer[];
  injuries?: Record<string, InjuryInfo>;
  onSelectPlayer: (id: number, name: string, opponent: string, isHome: boolean) => void;
}) {
  return (
    <div>
      <h4 className="font-display text-lg text-chalk mb-3 flex items-center gap-2">
        <span className="text-dust text-sm font-sans uppercase tracking-widest">
          {team.city}
        </span>
        <span>{team.name}</span>
      </h4>
      <ul className="space-y-1">
        {players.map((p) => (
          <li key={p.id}>
            <button
              onClick={() => onSelectPlayer(p.id, p.name, opponent, isHome)}
              className="w-full text-left px-3 py-2 rounded-lg flex items-center gap-3 hover:bg-sideline/60 transition-colors group"
            >
              <span className="text-dust text-xs font-mono w-5 text-right flex-shrink-0">
                {p.number}
              </span>
              <span className="text-chalk text-sm group-hover:text-gold transition-colors flex-1 truncate">
                {p.name}
              </span>
              <div className="flex items-center gap-1.5 flex-shrink-0">
                {injuryBadge(p.name, injuries)}
                <span className="text-dust text-xs">{p.position}</span>
              </div>
            </button>
          </li>
        ))}
        {players.length === 0 && (
          <li className="text-dust text-sm py-2 px-3">No roster data</li>
        )}
      </ul>
    </div>
  );
}
