"use client";

import { useEffect, useState } from "react";
import { getHealth, SnapshotHealth } from "@/lib/api";

/**
 * Says when the served data is from.
 *
 * Predictions are precomputed by a job that runs once a day, so last night's
 * games do not appear until the next refresh. Without this the UI reads as a
 * live feed and quietly misleads.
 */
export default function DataFreshness() {
    const [health, setHealth] = useState<SnapshotHealth | null>(null);

    useEffect(() => {
        getHealth().then(setHealth);
    }, []);

    if (!health) return null;

    if (!health.snapshot_loaded) {
        return (
            <span className="text-xs font-mono text-red-400" title="The API has no data snapshot loaded.">
                no data
            </span>
        );
    }

    const built = health.snapshot_built_at ? new Date(health.snapshot_built_at) : null;
    const label = built
        ? built.toLocaleDateString(undefined, { month: "short", day: "numeric" })
        : "unknown";

    const hours = health.snapshot_age_hours;
    const ago =
        hours == null ? "" : hours < 1 ? "just now" : hours < 24
            ? `${Math.round(hours)}h ago`
            : `${Math.round(hours / 24)}d ago`;

    return (
        <span
            className={`text-xs font-mono ${health.stale ? "text-gold" : "text-dust"}`}
            title={
                `Predictions are precomputed daily, not live.\n` +
                `Snapshot built ${health.snapshot_built_at} (${ago}).\n` +
                `Games through ${health.data_through}.\n` +
                `${health.n_predictions} players projected.`
            }
        >
            {health.stale ? "stale data" : "data"} · {label}
        </span>
    );
}
