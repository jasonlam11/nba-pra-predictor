"use client";

import { PinnedPlayer } from "@/lib/usePinnedPlayers";

interface PinnedPlayersProps {
  players: PinnedPlayer[];
  onSelect: (id: number, name: string) => void;
  onUnpin: (id: number, name: string) => void;
}

export default function PinnedPlayers({
  players,
  onSelect,
  onUnpin,
}: PinnedPlayersProps) {
  if (players.length === 0) return null;

  return (
    <section className="mb-8">
      <h2 className="font-display text-xl text-dust uppercase tracking-widest mb-3">
        Pinned Players
      </h2>
      <div className="flex flex-wrap gap-2">
        {players.map((p) => (
          <div
            key={p.id}
            className="flex items-center gap-1 bg-hardwood border border-sideline rounded-lg pl-4 pr-2 py-2 group hover:border-gold/40 transition-colors"
          >
            <button
              onClick={() => onSelect(p.id, p.name)}
              className="text-chalk text-sm font-medium hover:text-gold transition-colors pr-2"
            >
              {p.name}
            </button>
            <button
              onClick={() => onUnpin(p.id, p.name)}
              className="text-dust hover:text-highlight transition-colors p-0.5 rounded"
              title="Unpin"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}
