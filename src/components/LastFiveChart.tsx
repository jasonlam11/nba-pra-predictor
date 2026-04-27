"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { GameLog, StatType } from "@/lib/api";

const STAT_COLOR: Record<StatType, string> = {
  pra: "#f1c40f",
  pts: "#f1c40f",
  reb: "#a8d5e5",
  ast: "#e94560",
};

const STAT_LABEL: Record<StatType, string> = {
  pra: "PRA",
  pts: "PTS",
  reb: "REB",
  ast: "AST",
};

const COL_COLOR: Record<StatType, string> = {
  pra: "text-chalk font-bold",
  pts: "text-gold",
  reb: "text-ice",
  ast: "text-highlight",
};

function getStatValue(game: GameLog, stat: StatType): number {
  if (stat === "pra") return game.points + game.rebounds + game.assists;
  if (stat === "pts") return game.points;
  if (stat === "reb") return game.rebounds;
  return game.assists;
}

const CustomTooltip = ({
  active,
  payload,
  label,
  stat,
}: {
  active?: boolean;
  payload?: any[];
  label?: string;
  stat: StatType;
}) => {
  if (active && payload && payload.length) {
    const val = payload[0].value;
    return (
      <div className="bg-hardwood border border-sideline rounded-lg px-4 py-3 shadow-xl">
        <p className="text-chalk font-medium mb-1">{label}</p>
        <p className="font-mono font-bold" style={{ color: STAT_COLOR[stat] }}>
          {STAT_LABEL[stat]}: {val}
        </p>
      </div>
    );
  }
  return null;
};

interface GameHistoryChartProps {
  games: GameLog[];
  selectedStat: StatType;
  propLine: number;
}

export default function GameHistoryChart({
  games,
  selectedStat,
  propLine,
}: GameHistoryChartProps) {
  if (!games || games.length === 0) {
    return (
      <div className="bg-hardwood border border-sideline rounded-xl p-6">
        <p className="text-dust text-center py-8">No game data available</p>
      </div>
    );
  }

  // Chart shows oldest → newest left to right
  const chartData = [...games]
    .reverse()
    .map((g) => ({
      opponent: `${g.home ? "vs" : "@"} ${g.opponent}`,
      value: getStatValue(g, selectedStat),
      result: g.result,
    }));

  const avg =
    games.reduce((sum, g) => sum + getStatValue(g, selectedStat), 0) /
    games.length;

  const color = STAT_COLOR[selectedStat];
  const label = STAT_LABEL[selectedStat];

  return (
    <div className="bg-hardwood border border-sideline rounded-xl p-6">
      <div className="flex items-center justify-between mb-6">
        <h3 className="font-display text-xl text-chalk">
          Last {games.length} Games — {label}
        </h3>
        <span className="text-dust text-xs font-mono">
          Avg {avg.toFixed(1)} · Line {propLine.toFixed(1)}
        </span>
      </div>

      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={chartData}
            margin={{ top: 8, right: 16, left: 0, bottom: 4 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#1a1a2e" />
            <XAxis
              dataKey="opponent"
              stroke="#1a1a2e"
              tick={{ fill: "#8b8b9e", fontSize: 10 }}
              interval="preserveStartEnd"
            />
            <YAxis
              stroke="#1a1a2e"
              tick={{ fill: "#8b8b9e", fontSize: 11 }}
              width={28}
            />
            <Tooltip
              content={(props) => (
                <CustomTooltip {...props} stat={selectedStat} />
              )}
            />
            {/* Average line */}
            <ReferenceLine
              y={avg}
              stroke="#8b8b9e"
              strokeDasharray="4 4"
              strokeWidth={1}
              label={{
                value: `Avg ${avg.toFixed(1)}`,
                position: "insideTopRight",
                fill: "#8b8b9e",
                fontSize: 10,
              }}
            />
            {/* Prop line */}
            <ReferenceLine
              y={propLine}
              stroke={color}
              strokeDasharray="6 3"
              strokeWidth={1.5}
              label={{
                value: `Line ${propLine.toFixed(1)}`,
                position: "insideBottomRight",
                fill: color,
                fontSize: 10,
              }}
            />
            <Line
              type="monotone"
              dataKey="value"
              name={label}
              stroke={color}
              strokeWidth={2.5}
              dot={{ fill: color, strokeWidth: 0, r: 4 }}
              activeDot={{ r: 6, fill: color, stroke: "#0d0d14", strokeWidth: 2 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Scrollable table */}
      <div className="mt-6 max-h-64 overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-hardwood">
            <tr className="border-b border-sideline">
              <th className="hidden sm:table-cell text-left text-dust font-medium uppercase tracking-widest py-2 pr-3 text-xs">Date</th>
              <th className="text-left text-dust font-medium uppercase tracking-widest py-2 pr-3 text-xs">Opp</th>
              <th className={`text-right font-medium uppercase tracking-widest py-2 pr-3 text-xs ${selectedStat === "pts" ? "text-gold" : "text-dust"}`}>PTS</th>
              <th className={`text-right font-medium uppercase tracking-widest py-2 pr-3 text-xs ${selectedStat === "reb" ? "text-ice" : "text-dust"}`}>REB</th>
              <th className={`text-right font-medium uppercase tracking-widest py-2 pr-3 text-xs ${selectedStat === "ast" ? "text-highlight" : "text-dust"}`}>AST</th>
              <th className={`text-right font-medium uppercase tracking-widest py-2 text-xs ${selectedStat === "pra" ? "text-gold" : "text-dust"}`}>PRA</th>
            </tr>
          </thead>
          <tbody>
            {games.map((game, i) => {
              const pra = game.points + game.rebounds + game.assists;
              const statVal = getStatValue(game, selectedStat);
              const hitLine = statVal > propLine;
              return (
                <tr
                  key={i}
                  className="border-b border-sideline/40 hover:bg-sideline/30 transition-colors"
                >
                  <td className="hidden sm:table-cell py-2.5 pr-3 text-dust text-xs whitespace-nowrap">{game.date}</td>
                  <td className="py-2.5 pr-3 text-chalk font-medium text-sm max-w-[80px] sm:max-w-none truncate">
                    {game.home ? "vs" : "@"} {game.opponent}
                  </td>
                  <td className={`py-2.5 pr-3 text-right font-mono text-sm ${selectedStat === "pts" ? "text-gold font-bold" : "text-chalk/70"}`}>
                    {game.points}
                  </td>
                  <td className={`py-2.5 pr-3 text-right font-mono text-sm ${selectedStat === "reb" ? "text-ice font-bold" : "text-chalk/70"}`}>
                    {game.rebounds}
                  </td>
                  <td className={`py-2.5 pr-3 text-right font-mono text-sm ${selectedStat === "ast" ? "text-highlight font-bold" : "text-chalk/70"}`}>
                    {game.assists}
                  </td>
                  <td className="py-2.5 text-right">
                    <span
                      className={`font-mono font-bold text-sm ${
                        selectedStat === "pra"
                          ? hitLine
                            ? "text-green-400"
                            : "text-highlight"
                          : "text-chalk/70"
                      }`}
                    >
                      {pra}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
