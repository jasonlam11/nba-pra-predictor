"use client";

import { useState, useRef } from "react";
import { Player, PlayerStats, StatType, searchPlayers, getPlayerStats } from "@/lib/api";
import { usePinnedPlayers } from "@/lib/usePinnedPlayers";

// ── types ────────────────────────────────────────────────────────────────────

interface SlotState {
  player: Player | null;
  stats: PlayerStats | null;
  loading: boolean;
  error: string | null;
  query: string;
  results: Player[];
  searching: boolean;
}

const emptySlot = (): SlotState => ({
  player: null,
  stats: null,
  loading: false,
  error: null,
  query: "",
  results: [],
  searching: false,
});

const STAT_LABELS: Record<StatType, string> = { pra: "PRA", pts: "PTS", reb: "REB", ast: "AST" };
const STAT_COLORS: Record<StatType, string> = {
  pra: "text-gold",
  pts: "text-gold",
  reb: "text-ice",
  ast: "text-highlight",
};

function getPred(stats: PlayerStats, stat: StatType): number {
  if (stat === "pra") return stats.prediction.total_pra;
  if (stat === "pts") return stats.prediction.points;
  if (stat === "reb") return stats.prediction.rebounds;
  return stats.prediction.assists;
}

function getAvg(stats: PlayerStats, stat: StatType): number {
  if (stat === "pra") return stats.season_avg.points + stats.season_avg.rebounds + stats.season_avg.assists;
  if (stat === "pts") return stats.season_avg.points;
  if (stat === "reb") return stats.season_avg.rebounds;
  return stats.season_avg.assists;
}

function getHitRate(stats: PlayerStats, stat: StatType, line: number): { hits: number; total: number } {
  const games = stats.last_20_games;
  const hits = games.filter((g) => {
    const val = stat === "pra" ? g.points + g.rebounds + g.assists
      : stat === "pts" ? g.points
      : stat === "reb" ? g.rebounds
      : g.assists;
    return val > line;
  }).length;
  return { hits, total: games.length };
}

// ── search input ─────────────────────────────────────────────────────────────

function SearchInput({
  slot,
  label,
  accentClass,
  onQueryChange,
  onSelect,
  onClear,
}: {
  slot: SlotState;
  label: string;
  accentClass: string;
  onQueryChange: (q: string) => void;
  onSelect: (p: Player) => void;
  onClear: () => void;
}) {
  return (
    <div className="flex-1 min-w-0">
      <p className={`text-xs uppercase tracking-widest font-bold mb-2 ${accentClass}`}>{label}</p>
      <div className="relative">
        <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-dust pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <input
          type="text"
          value={slot.query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="Search player..."
          className="w-full bg-hardwood border border-sideline rounded-xl pl-9 pr-8 py-2.5 text-chalk placeholder-dust/50 focus:outline-none focus:border-gold/60 transition-colors text-sm"
        />
        {slot.query && (
          <button onClick={onClear} className="absolute right-3 top-1/2 -translate-y-1/2 text-dust hover:text-chalk">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>
      {slot.results.length > 0 && (
        <div className="mt-1 bg-hardwood border border-sideline rounded-xl overflow-hidden shadow-lg z-10 relative">
          {slot.results.map((p) => (
            <button
              key={p.id}
              onClick={() => onSelect(p)}
              className="w-full text-left px-4 py-2.5 text-sm text-chalk hover:bg-sideline transition-colors border-b border-sideline/50 last:border-0"
            >
              {p.full_name}
            </button>
          ))}
        </div>
      )}
      {slot.searching && (
        <div className="mt-2 flex items-center gap-2 text-dust text-xs">
          <div className="w-3 h-3 border-2 border-gold border-t-transparent rounded-full animate-spin" />
          Searching...
        </div>
      )}
    </div>
  );
}

// ── player card ───────────────────────────────────────────────────────────────

function PlayerCard({
  slot,
  stat,
  line,
  accentClass,
  isPinned,
  onTogglePin,
}: {
  slot: SlotState;
  stat: StatType;
  line: number;
  accentClass: string;
  isPinned: (id: number) => boolean;
  onTogglePin: (id: number, name: string) => void;
}) {
  if (slot.loading) {
    return (
      <div className="flex-1 bg-hardwood border border-sideline rounded-xl p-8 flex flex-col items-center justify-center gap-3 min-h-[260px]">
        <div className="w-10 h-10 border-4 border-gold border-t-transparent rounded-full animate-spin" />
        <p className="text-dust text-sm">Loading...</p>
      </div>
    );
  }

  if (slot.error) {
    return (
      <div className="flex-1 bg-hardwood border border-sideline rounded-xl p-8 flex flex-col items-center justify-center min-h-[260px]">
        <p className="text-highlight text-sm text-center">{slot.error}</p>
      </div>
    );
  }

  if (!slot.stats || !slot.player) {
    return (
      <div className="flex-1 bg-hardwood border border-sideline rounded-xl p-8 flex flex-col items-center justify-center min-h-[260px]">
        <p className="text-dust/50 text-sm">Select a player above</p>
      </div>
    );
  }

  const { stats, player } = slot;
  const pred = getPred(stats, stat);
  const avg = getAvg(stats, stat);
  const { hits, total } = getHitRate(stats, stat, line);
  const hitRate = total > 0 ? hits / total : 0;
  const isOver = pred > line;
  const diff = Math.abs(pred - line);
  const barColor = hitRate >= 0.7 ? "bg-green-500" : hitRate >= 0.4 ? "bg-gold" : "bg-highlight";

  return (
    <div className="flex-1 bg-hardwood border border-sideline rounded-xl p-5 space-y-5">
      {/* Name + pin */}
      <div className="flex items-center gap-2">
        <h3 className="font-display text-xl text-chalk leading-tight">{player.full_name}</h3>
        <button
          onClick={() => onTogglePin(player.id, player.full_name)}
          title={isPinned(player.id) ? "Unpin" : "Pin"}
          className="flex-shrink-0 transition-transform hover:scale-110 active:scale-95"
        >
          {isPinned(player.id) ? (
            <svg className="w-5 h-5 text-gold" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
            </svg>
          ) : (
            <svg className="w-5 h-5 text-dust hover:text-gold transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
            </svg>
          )}
        </button>
      </div>

      {/* Prediction vs line */}
      <div className={`rounded-xl p-4 flex items-center justify-between border ${isOver ? "bg-green-500/10 border-green-500/30" : "bg-highlight/10 border-highlight/30"}`}>
        <div>
          <p className="text-dust text-xs uppercase tracking-widest mb-1">Model Projection</p>
          <p className={`stat-number text-4xl font-bold ${isOver ? "text-green-400" : "text-highlight"}`}>
            {pred.toFixed(1)}
          </p>
        </div>
        <div className="text-right">
          <p className={`font-display text-2xl ${isOver ? "text-green-400" : "text-highlight"}`}>
            {isOver ? "▲ OVER" : "▼ UNDER"}
          </p>
          <p className="text-dust text-sm">by {diff.toFixed(1)}</p>
        </div>
      </div>

      {/* Season avg */}
      <div className="flex gap-4">
        {(["pts", "reb", "ast"] as const).map((s) => {
          const labels = { pts: "PTS", reb: "REB", ast: "AST" };
          const colors = { pts: "text-gold", reb: "text-ice", ast: "text-highlight" };
          const vals = { pts: stats.season_avg.points, reb: stats.season_avg.rebounds, ast: stats.season_avg.assists };
          return (
            <div key={s} className="flex-1 text-center bg-sideline/40 rounded-lg py-3">
              <p className={`stat-number text-xl font-bold ${colors[s]}`}>{vals[s].toFixed(1)}</p>
              <p className="text-dust text-xs uppercase tracking-widest mt-0.5">{labels[s]}</p>
            </div>
          );
        })}
      </div>

      {/* Hit rate */}
      {total > 0 && (
        <div>
          <div className="flex justify-between items-center mb-1.5">
            <span className="text-dust text-xs">Hit rate — last {total} games</span>
            <span className="text-chalk font-mono font-bold text-xs">
              {hits}/{total} <span className="text-dust font-normal">({Math.round(hitRate * 100)}%)</span>
            </span>
          </div>
          <div className="h-2 bg-sideline rounded-full overflow-hidden">
            <div className={`h-full rounded-full transition-all duration-500 ${barColor}`} style={{ width: `${hitRate * 100}%` }} />
          </div>
          <div className="flex gap-0.5 mt-1.5">
            {stats.last_20_games.map((g, i) => {
              const val = stat === "pra" ? g.points + g.rebounds + g.assists
                : stat === "pts" ? g.points
                : stat === "reb" ? g.rebounds
                : g.assists;
              return (
                <div
                  key={i}
                  title={`${g.date}: ${val}`}
                  className={`flex-1 h-1.5 rounded-full ${val > line ? barColor : "bg-sideline"}`}
                />
              );
            })}
          </div>
        </div>
      )}

      {/* Confidence */}
      <div className="flex items-center justify-between border-t border-sideline pt-4">
        <span className="text-dust text-xs uppercase tracking-widest">Confidence</span>
        <span className={`stat-number text-lg font-bold ${accentClass}`}>{stats.prediction.confidence}%</span>
      </div>
    </div>
  );
}

// ── main page ─────────────────────────────────────────────────────────────────

export default function ComparePage() {
  const [slotA, setSlotA] = useState<SlotState>(emptySlot());
  const [slotB, setSlotB] = useState<SlotState>(emptySlot());
  const [selectedStat, setSelectedStat] = useState<StatType>("pra");
  const [propLine, setPropLine] = useState<number>(25);
  const { isPinned, togglePin } = usePinnedPlayers();

  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const handleQuery = (side: "a" | "b", val: string) => {
    const setter = side === "a" ? setSlotA : setSlotB;
    setter((s) => ({ ...s, query: val, results: val.length < 2 ? [] : s.results }));

    clearTimeout(timers.current[side]);
    if (val.length < 2) return;

    timers.current[side] = setTimeout(async () => {
      setter((s) => ({ ...s, searching: true }));
      const data = await searchPlayers(val);
      setter((s) => ({ ...s, results: data.slice(0, 15), searching: false }));
    }, 300);
  };

  const handleSelect = async (side: "a" | "b", player: Player) => {
    const setter = side === "a" ? setSlotA : setSlotB;
    setter((s) => ({ ...s, player, query: player.full_name, results: [], loading: true, error: null, stats: null }));

    const { data: stats, error } = await getPlayerStats(player.id);
    if (stats) {
      setter((prev) => {
        const otherHasData = side === "a" ? slotB.stats !== null : slotA.stats !== null;
        if (!otherHasData) {
          setPropLine(Math.round(getPred(stats, selectedStat) * 2) / 2);
        }
        return { ...prev, stats, loading: false };
      });
    } else {
      setter((s) => ({ ...s, loading: false, error: error ?? "Failed to load stats." }));
    }
  };

  const handleClear = (side: "a" | "b") => {
    (side === "a" ? setSlotA : setSlotB)(emptySlot());
  };

  const handleStatChange = (stat: StatType) => {
    setSelectedStat(stat);
    // Re-sync line to player A's prediction for the new stat (if loaded)
    if (slotA.stats) {
      setPropLine(Math.round(getPred(slotA.stats, stat) * 2) / 2);
    } else if (slotB.stats) {
      setPropLine(Math.round(getPred(slotB.stats, stat) * 2) / 2);
    }
  };

  // Verdict banner
  const bothLoaded = slotA.stats && slotB.stats;
  const predA = slotA.stats ? getPred(slotA.stats, selectedStat) : null;
  const predB = slotB.stats ? getPred(slotB.stats, selectedStat) : null;
  const hitA = slotA.stats ? getHitRate(slotA.stats, selectedStat, propLine) : null;
  const hitB = slotB.stats ? getHitRate(slotB.stats, selectedStat, propLine) : null;
  const rateA = hitA && hitA.total > 0 ? hitA.hits / hitA.total : null;
  const rateB = hitB && hitB.total > 0 ? hitB.hits / hitB.total : null;

  let verdictText = "";
  if (bothLoaded && predA !== null && predB !== null && rateA !== null && rateB !== null) {
    const nameA = slotA.player!.full_name.split(" ").pop()!;
    const nameB = slotB.player!.full_name.split(" ").pop()!;
    const overA = predA > propLine;
    const overB = predB > propLine;

    if (overA && !overB) verdictText = `${nameA} is the better OVER — model projects ${predA.toFixed(1)} vs line ${propLine.toFixed(1)}`;
    else if (overB && !overA) verdictText = `${nameB} is the better OVER — model projects ${predB.toFixed(1)} vs line ${propLine.toFixed(1)}`;
    else if (overA && overB) {
      const pick = rateA >= rateB ? nameA : nameB;
      const rate = Math.round(Math.max(rateA, rateB) * 100);
      verdictText = `Both project OVER — ${pick} has the stronger hit rate at ${rate}%`;
    } else {
      verdictText = `Both project UNDER ${propLine.toFixed(1)} ${STAT_LABELS[selectedStat]}`;
    }
  }

  return (
    <main className="max-w-5xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
      <h2 className="font-display text-3xl text-chalk mb-2">Compare Players</h2>
      <p className="text-dust text-sm mb-8">Pick two players and a prop line to compare projections head-to-head.</p>

      {/* Player search row */}
      <div className="flex flex-col sm:flex-row items-start gap-4 mb-6">
        <SearchInput
          slot={slotA}
          label="Player A"
          accentClass="text-gold"
          onQueryChange={(q) => handleQuery("a", q)}
          onSelect={(p) => handleSelect("a", p)}
          onClear={() => handleClear("a")}
        />
        <div className="hidden sm:flex items-center self-center pt-6 text-dust font-display text-xl">vs</div>
        <SearchInput
          slot={slotB}
          label="Player B"
          accentClass="text-ice"
          onQueryChange={(q) => handleQuery("b", q)}
          onSelect={(p) => handleSelect("b", p)}
          onClear={() => handleClear("b")}
        />
      </div>

      {/* Shared controls */}
      <div className="bg-hardwood border border-sideline rounded-xl p-4 mb-6 flex flex-wrap items-center gap-4">
        {/* Stat tabs */}
        <div className="flex gap-2">
          {(["pra", "pts", "reb", "ast"] as StatType[]).map((stat) => (
            <button
              key={stat}
              onClick={() => handleStatChange(stat)}
              className={`px-3 py-1.5 rounded-lg text-sm font-mono font-bold transition-colors ${
                selectedStat === stat
                  ? `bg-gold/20 border border-gold/60 ${STAT_COLORS[stat]}`
                  : "bg-sideline text-dust hover:text-chalk border border-transparent"
              }`}
            >
              {STAT_LABELS[stat]}
            </button>
          ))}
        </div>

        {/* Divider */}
        <div className="hidden sm:block h-6 w-px bg-sideline" />

        {/* Line input */}
        <div className="flex items-center gap-3">
          <span className="text-dust text-xs uppercase tracking-widest">Line</span>
          <button
            onClick={() => setPropLine((l) => Math.max(0, +(l - 0.5).toFixed(1)))}
            className="w-8 h-8 rounded-lg bg-sideline border border-sideline hover:border-dust text-chalk text-lg flex items-center justify-center transition-colors"
          >
            −
          </button>
          <span className="stat-number text-2xl text-chalk w-16 text-center tabular-nums">
            {propLine.toFixed(1)}
          </span>
          <button
            onClick={() => setPropLine((l) => +(l + 0.5).toFixed(1))}
            className="w-8 h-8 rounded-lg bg-sideline border border-sideline hover:border-dust text-chalk text-lg flex items-center justify-center transition-colors"
          >
            +
          </button>
        </div>
      </div>

      {/* Verdict banner */}
      {verdictText && (
        <div className="mb-6 bg-gold/10 border border-gold/30 rounded-xl px-5 py-3 flex items-center gap-3 animate-fade-in">
          <svg className="w-4 h-4 text-gold flex-shrink-0" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
          </svg>
          <p className="text-chalk text-sm">{verdictText}</p>
        </div>
      )}

      {/* Side-by-side cards */}
      <div className="flex flex-col sm:flex-row gap-4">
        <PlayerCard
          slot={slotA}
          stat={selectedStat}
          line={propLine}
          accentClass="text-gold"
          isPinned={isPinned}
          onTogglePin={togglePin}
        />
        <PlayerCard
          slot={slotB}
          stat={selectedStat}
          line={propLine}
          accentClass="text-ice"
          isPinned={isPinned}
          onTogglePin={togglePin}
        />
      </div>
    </main>
  );
}
