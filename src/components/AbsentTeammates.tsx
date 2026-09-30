"use client";

import { AbsentTeammate } from "@/lib/api";

/**
 * Rotation teammates ruled out for the upcoming game.
 *
 * Worth showing on its own terms: whoever is out is usually the single most
 * actionable piece of context for a prop decision, and their minutes have to go
 * somewhere. The model also reads this (TEAM_MIN_ABSENT), but the list is
 * useful even where the model's own adjustment is small.
 */
export default function AbsentTeammates({
    teammates,
    totalMinutes,
}: {
    teammates?: AbsentTeammate[];
    totalMinutes?: number;
}) {
    if (!teammates || teammates.length === 0) return null;

    return (
        <div className="bg-hardwood border border-sideline rounded-xl p-4">
            <div className="flex items-baseline justify-between mb-2.5">
                <h4 className="font-display text-sm text-gold uppercase tracking-widest">
                    Teammates Out
                </h4>
                {totalMinutes ? (
                    <span className="text-xs font-mono text-dust">
                        {totalMinutes.toFixed(0)} mpg up for grabs
                    </span>
                ) : null}
            </div>

            <ul className="space-y-1.5">
                {teammates.map((t) => (
                    <li key={t.name} className="flex items-center justify-between gap-3 text-sm">
                        <span className="text-chalk truncate">{t.name}</span>
                        <span className="flex items-center gap-2 shrink-0">
                            <span className="font-mono text-dust text-xs">
                                {t.minutes.toFixed(1)} mpg
                            </span>
                            <span
                                className={`font-mono text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded ${
                                    t.status.toLowerCase() === "out"
                                        ? "bg-red-500/15 text-red-400"
                                        : "bg-gold/15 text-gold"
                                }`}
                            >
                                {t.status}
                            </span>
                        </span>
                    </li>
                ))}
            </ul>
        </div>
    );
}
