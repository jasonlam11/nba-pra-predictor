import { TeamDefense, InjuryInfo } from "@/lib/api";

interface PRACardProps {
    points: number;
    rebounds: number;
    assists: number;
    opponent: string;
    gameTime: string;
    isHome: boolean;
    confidence?: number;
    defense?: TeamDefense | null;
    injuryStatus?: InjuryInfo | null;
}

export default function PRACard({
    points,
    rebounds,
    assists,
    opponent,
    gameTime,
    isHome,
    confidence = 75,
    defense = null,
    injuryStatus = null,
}: PRACardProps) {
    const totalPRA = points + rebounds + assists;

    return (
        <div className="glow-border bg-hardwood rounded-xl p-6 border border-gold/30">
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div>
                    <p className="text-dust text-xs uppercase tracking-widest mb-1">
                        Predicted PRA
                    </p>
                    <p className="stat-number text-5xl font-bold text-gold">
                        {totalPRA.toFixed(1)}
                    </p>
                </div>

                {/* Confidence meter */}
                <div className="text-right">
                    <p className="text-dust text-xs uppercase tracking-widest mb-1">
                        Confidence
                    </p>
                    <p className="stat-number text-2xl font-bold text-chalk">
                        {confidence}%
                    </p>
                </div>
            </div>

            {/* Individual stats */}
            <div className="grid grid-cols-3 gap-4 mb-6">
                <div className="text-center">
                    <p className="stat-number text-3xl font-bold text-gold">{points.toFixed(1)}</p>
                    <p className="text-dust text-xs uppercase tracking-widest mt-1">PTS</p>
                </div>
                <div className="text-center">
                    <p className="stat-number text-3xl font-bold text-ice">{rebounds.toFixed(1)}</p>
                    <p className="text-dust text-xs uppercase tracking-widest mt-1">REB</p>
                </div>
                <div className="text-center">
                    <p className="stat-number text-3xl font-bold text-highlight">{assists.toFixed(1)}</p>
                    <p className="text-dust text-xs uppercase tracking-widest mt-1">AST</p>
                </div>
            </div>

            {/* Game info */}
            <div className="border-t border-sideline pt-4 space-y-2">
                <p className="text-dust text-sm">
                    {isHome ? "vs" : "@"} <span className="text-chalk font-medium">{opponent}</span>
                    <span className="mx-2">•</span>
                    {gameTime}
                </p>

                {/* Injury alert */}
                {injuryStatus && (
                    <div className={`flex items-center gap-2 text-xs px-2 py-1 rounded-lg border w-fit ${
                        injuryStatus.status.toLowerCase() === "out" || injuryStatus.status.toLowerCase() === "doubtful"
                            ? "bg-highlight/10 border-highlight/30 text-highlight"
                            : "bg-gold/10 border-gold/30 text-gold"
                    }`}>
                        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                        </svg>
                        <span className="font-medium">{injuryStatus.status}</span>
                        {injuryStatus.description && injuryStatus.description !== injuryStatus.status && (
                            <span className="opacity-70">— {injuryStatus.description}</span>
                        )}
                    </div>
                )}

                {/* Opponent defense */}
                {defense && opponent !== "—" && (
                    <div className="flex items-center gap-4 text-xs">
                        <div className="flex items-center gap-1.5">
                            <span className="text-dust">Opp allows</span>
                            <span className="text-chalk font-mono font-bold">{defense.pts_allowed} PPG</span>
                            <span className={`font-mono font-bold ${
                                defense.pts_rank > 20 ? "text-green-400" :
                                defense.pts_rank < 11 ? "text-highlight" : "text-gold"
                            }`}>
                                (#{defense.pts_rank} defense)
                            </span>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}