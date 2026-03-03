interface PRACardProps {
    points: number;
    rebounds: number;
    assists: number;
    opponent: string;
    gameTime: string;
    isHome: boolean;
    confidence?: number;
}

export default function PRACard({
    points,
    rebounds,
    assists,
    opponent,
    gameTime,
    isHome,
    confidence = 75,
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
            <div className="border-t border-sideline pt-4">
                <p className="text-dust text-sm">
                    {isHome ? "vs" : "@"} <span className="text-chalk font-medium">{opponent}</span>
                    <span className="mx-2">•</span>
                    {gameTime}
                </p>
            </div>
        </div>
    );
}