"use client";

import { useState, useEffect } from "react";

export interface PinnedPlayer {
  id: number;
  name: string;
}

const STORAGE_KEY = "pra_pinned_players";

export function usePinnedPlayers() {
  const [pinned, setPinned] = useState<PinnedPlayer[]>([]);
  const [ready, setReady] = useState(false);

  // Load from localStorage once on mount
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) setPinned(JSON.parse(saved));
    } catch {
      // ignore corrupt storage
    }
    setReady(true);
  }, []);

  const isPinned = (id: number) => pinned.some((p) => p.id === id);

  const togglePin = (id: number, name: string) => {
    setPinned((prev) => {
      const next = isPinned(id)
        ? prev.filter((p) => p.id !== id)
        : [...prev, { id, name }];
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  };

  return { pinned, isPinned, togglePin, ready };
}
