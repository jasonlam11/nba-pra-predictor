"use client";

import { Prediction, GameLog, StatReasons, Reason, StatType } from "@/lib/api";

const STAT_LABELS: Record<StatType, string> = {
  pra: "PRA",
  pts: "PTS",
  reb: "REB",
  ast: "AST",
};

const STAT_COLORS: Record<StatType, string> = {
  pra: "text-gold",
  pts: "text-gold",
  reb: "text-ice",
  ast: "text-highlight",
};

function getModelPrediction(prediction: Prediction, stat: StatType): number {
  if (stat === "pra") return prediction.total_pra;
  if (stat === "pts") return prediction.points;
  if (stat === "reb") return prediction.rebounds;
  return prediction.assists;
}

function getStatValue(game: GameLog, stat: StatType): number {
  if (stat === "pra") return game.points + game.rebounds + game.assists;
  if (stat === "pts") return game.points;
  if (stat === "reb") return game.rebounds;
  return game.assists;
}

function roundToHalf(n: number): number {
  return Math.round(n * 2) / 2;
}

interface PropLineAnalyzerProps {
  prediction: Prediction;
  last20Games: GameLog[];
  reasons: StatReasons;
  selectedStat: StatType;
  onStatChange: (stat: StatType) => void;
  line: number;
  onLineChange: (line: number) => void;
}

export default function PropLineAnalyzer({
  prediction,
  last20Games,
  reasons,
  selectedStat,
  onStatChange,
  line,
  onLineChange,
}: PropLineAnalyzerProps) {
  const modelPred = getModelPrediction(prediction, selectedStat);
  const isOver = modelPred > line;
  const diff = Math.abs(modelPred - line);

  const hits = last20Games.filter(
    (g) => getStatValue(g, selectedStat) > line
  ).length;
  const total = last20Games.length;
  const hitRate = total > 0 ? hits / total : 0;

  const verdictColor = isOver ? "text-green-400" : "text-highlight";
  const verdictBg = isOver
    ? "bg-green-500/10 border-green-500/30"
    : "bg-highlight/10 border-highlight/30";
  const barColor =
    hitRate >= 0.7 ? "bg-green-500" : hitRate >= 0.4 ? "bg-gold" : "bg-highlight";

  const handleStatChange = (stat: StatType) => {
    onStatChange(stat);
    onLineChange(roundToHalf(getModelPrediction(prediction, stat)));
  };

  const currentReasons = reasons[selectedStat] ?? [];

  return (
    <div className="bg-hardwood border border-sideline rounded-xl p-6">
      <h3 className="font-display text-xl text-chalk mb-5">Prop Line Analyzer</h3>

      {/* Stat type tabs */}
      <div className="flex flex-wrap gap-2 mb-6">
        {(["pra", "pts", "reb", "ast"] as StatType[]).map((stat) => (
          <button
            key={stat}
            onClick={() => handleStatChange(stat)}
            className={`px-4 py-1.5 rounded-lg text-sm font-mono font-bold transition-colors ${
              selectedStat === stat
                ? `bg-gold/20 border border-gold/60 ${STAT_COLORS[stat]}`
                : "bg-sideline text-dust hover:text-chalk border border-transparent"
            }`}
          >
            {STAT_LABELS[stat]}
          </button>
        ))}
      </div>

      {/* Line input */}
      <div className="flex items-center gap-4 mb-6">
        <span className="text-dust text-sm uppercase tracking-widest w-10">Line</span>
        <div className="flex items-center gap-3">
          <button
            onClick={() => onLineChange(Math.max(0, +(line - 0.5).toFixed(1)))}
            className="w-9 h-9 rounded-lg bg-sideline border border-sideline hover:border-dust text-chalk text-xl flex items-center justify-center transition-colors"
          >
            −
          </button>
          <span className="stat-number text-4xl text-chalk w-24 text-center tabular-nums">
            {line.toFixed(1)}
          </span>
          <button
            onClick={() => onLineChange(+(line + 0.5).toFixed(1))}
            className="w-9 h-9 rounded-lg bg-sideline border border-sideline hover:border-dust text-chalk text-xl flex items-center justify-center transition-colors"
          >
            +
          </button>
        </div>
      </div>

      {/* Model verdict */}
      <div
        className={`rounded-xl p-4 mb-6 flex items-center justify-between border ${verdictBg}`}
      >
        <div>
          <p className="text-dust text-xs uppercase tracking-widest mb-1">
            Model Projection
          </p>
          <p className={`stat-number text-3xl font-bold ${verdictColor}`}>
            {modelPred.toFixed(1)}
          </p>
        </div>
        <div className="text-right">
          <p className={`font-display text-2xl ${verdictColor}`}>
            {isOver ? "▲ OVER" : "▼ UNDER"}
          </p>
          <p className="text-dust text-sm">by {diff.toFixed(1)}</p>
        </div>
      </div>

      {/* Hit rate */}
      {total > 0 && (
        <div className="mb-6">
          <div className="flex justify-between items-center mb-2">
            <span className="text-dust text-sm">
              Hit rate — last {total} games
            </span>
            <span className="text-chalk font-mono font-bold text-sm">
              {hits}/{total}{" "}
              <span className="text-dust font-normal">
                ({Math.round(hitRate * 100)}%)
              </span>
            </span>
          </div>
          <div className="h-2 bg-sideline rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${barColor}`}
              style={{ width: `${hitRate * 100}%` }}
            />
          </div>
          {/* Mini game dots */}
          <div className="flex gap-1 mt-2">
            {last20Games.map((g, i) => {
              const val = getStatValue(g, selectedStat);
              const hit = val > line;
              return (
                <div
                  key={i}
                  title={`${g.date}: ${val} ${STAT_LABELS[selectedStat]}`}
                  className={`flex-1 h-1.5 rounded-full ${
                    hit ? barColor : "bg-sideline"
                  }`}
                />
              );
            })}
          </div>
        </div>
      )}

      {/* Reasons */}
      {currentReasons.length > 0 && (
        <div>
          <p className="text-dust text-xs uppercase tracking-widest mb-3">
            Context
          </p>
          <ul className="space-y-2.5">
            {currentReasons.map((reason: Reason, i: number) => (
              <li key={i} className="flex items-start gap-2.5 text-sm">
                <span className={`mt-0.5 flex-shrink-0 font-bold ${reason.positive ? "text-green-400" : "text-highlight"}`}>
                  {reason.positive ? "↑" : "↓"}
                </span>
                <span className="text-chalk/80">{reason.text}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
