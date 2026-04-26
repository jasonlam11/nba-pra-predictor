"use client";

import {
    LineChart,
    Line,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
    Legend,
} from "recharts";

interface GameLog {
    date: string;
    opponent: string;
    home: boolean;
    points: number;
    rebounds: number;
    assists: number;
    minutes: number;
    result: string;
}

interface LastFiveChartProps {
    games: GameLog[];
}

const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
        return (
            <div className="bg-hardwood border border-sideline rounded-lg p-4 shadow-xl">
                <p className="text-chalk font-medium mb-2">{label}</p>
                {payload.map((entry: any, index: number) => (
                    <p key={index} className="text-sm" style={{ color: entry.color }}>
                        {entry.name}: <span className="font-mono font-bold">{entry.value}</span>
                    </p>
                ))}
            </div>
        );
    }
    return null;
};

export default function LastFiveChart({ games }: LastFiveChartProps) {
    if (!games || games.length === 0) {
        return (
            <div className="bg-hardwood border border-sideline rounded-xl p-6">
                <h3 className="font-display text-xl text-chalk mb-6">Last 5 Games</h3>
                <p className="text-dust text-center py-8">No game data available</p>
            </div>
        );
    }

    const chartData = [...games].reverse();

    return (
        <div className="bg-hardwood border border-sideline rounded-xl p-6">
            <h3 className="font-display text-xl text-chalk mb-6">Last 5 Games</h3>

            <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1a1a2e" />
                        <XAxis
                            dataKey="opponent"
                            stroke="#8b8b9e"
                            tick={{ fill: "#8b8b9e", fontSize: 12 }}
                            axisLine={{ stroke: "#1a1a2e" }}
                        />
                        <YAxis
                            stroke="#8b8b9e"
                            tick={{ fill: "#8b8b9e", fontSize: 12 }}
                            axisLine={{ stroke: "#1a1a2e" }}
                        />
                        <Tooltip content={<CustomTooltip />} />
                        <Legend
                            wrapperStyle={{ paddingTop: "20px" }}
                            formatter={(value) => <span className="text-dust text-sm">{value}</span>}
                        />
                        <Line
                            type="monotone"
                            dataKey="points"
                            name="Points"
                            stroke="#f1c40f"
                            strokeWidth={3}
                            dot={{ fill: "#f1c40f", strokeWidth: 2, r: 5 }}
                            activeDot={{ r: 7, fill: "#f1c40f", stroke: "#0d0d14", strokeWidth: 2 }}
                        />
                        <Line
                            type="monotone"
                            dataKey="rebounds"
                            name="Rebounds"
                            stroke="#a8d5e5"
                            strokeWidth={3}
                            dot={{ fill: "#a8d5e5", strokeWidth: 2, r: 5 }}
                            activeDot={{ r: 7, fill: "#a8d5e5", stroke: "#0d0d14", strokeWidth: 2 }}
                        />
                        <Line
                            type="monotone"
                            dataKey="assists"
                            name="Assists"
                            stroke="#e94560"
                            strokeWidth={3}
                            dot={{ fill: "#e94560", strokeWidth: 2, r: 5 }}
                            activeDot={{ r: 7, fill: "#e94560", stroke: "#0d0d14", strokeWidth: 2 }}
                        />
                    </LineChart>
                </ResponsiveContainer>
            </div>

            {/* Game Details Table */}
            <div className="mt-6 overflow-x-auto">
                <table className="w-full text-sm">
                    <thead>
                        <tr className="border-b border-sideline">
                            <th className="text-left text-dust font-medium uppercase tracking-widest py-2">Date</th>
                            <th className="text-left text-dust font-medium uppercase tracking-widest py-2">Opp</th>
                            <th className="text-right text-gold font-medium uppercase tracking-widest py-2">PTS</th>
                            <th className="text-right text-ice font-medium uppercase tracking-widest py-2">REB</th>
                            <th className="text-right text-highlight font-medium uppercase tracking-widest py-2">AST</th>
                            <th className="text-right text-dust font-medium uppercase tracking-widest py-2">PRA</th>
                        </tr>
                    </thead>
                    <tbody>
                        {games.map((game, index) => (
                            <tr key={index} className="border-b border-sideline/50 hover:bg-sideline/30 transition-colors">
                                <td className="py-3 text-dust">{game.date}</td>
                                <td className="py-3 text-chalk font-medium">{game.opponent}</td>
                                <td className="py-3 text-right font-mono text-gold">{game.points}</td>
                                <td className="py-3 text-right font-mono text-ice">{game.rebounds}</td>
                                <td className="py-3 text-right font-mono text-highlight">{game.assists}</td>
                                <td className="py-3 text-right font-mono text-chalk font-bold">
                                    {game.points + game.rebounds + game.assists}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}