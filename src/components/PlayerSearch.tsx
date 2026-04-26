"use client";

import { useState, useEffect } from "react";
import { searchPlayers, Player } from "@/lib/api";

interface PlayerSearchProps {
    onSelectPlayer: (player: Player) => void;
}

export default function PlayerSearch({ onSelectPlayer }: PlayerSearchProps) {
    const [query, setQuery] = useState("");
    const [isOpen, setIsOpen] = useState(false);
    const [players, setPlayers] = useState<Player[]>([]);
    const [isLoading, setIsLoading] = useState(false);

    // Debounced search
    useEffect(() => {
        if (query.length < 2) {
            setPlayers([]);
            return;
        }

        const timer = setTimeout(async () => {
            setIsLoading(true);
            const results = await searchPlayers(query);
            setPlayers(results);
            setIsLoading(false);
        }, 300);

        return () => clearTimeout(timer);
    }, [query]);

    const handleSelect = (player: Player) => {
        onSelectPlayer(player);
        setQuery(player.full_name);
        setIsOpen(false);
    };

    return (
        <div className="relative w-full max-w-md">
            <div className="relative">
                <input
                    type="text"
                    value={query}
                    onChange={(e) => {
                        setQuery(e.target.value);
                        setIsOpen(true);
                    }}
                    onFocus={() => setIsOpen(true)}
                    placeholder="Search for a player..."
                    className="w-full bg-hardwood border border-sideline rounded-lg px-4 py-3 pl-12 text-chalk placeholder-dust focus:outline-none focus:border-gold focus:ring-1 focus:ring-gold transition-all"
                />
                <svg
                    className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-dust"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                >
                    <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                    />
                </svg>
                {isLoading && (
                    <div className="absolute right-4 top-1/2 -translate-y-1/2">
                        <div className="w-5 h-5 border-2 border-gold border-t-transparent rounded-full animate-spin" />
                    </div>
                )}
            </div>

            {isOpen && query.length >= 2 && (
                <div className="absolute top-full left-0 right-0 mt-2 bg-hardwood border border-sideline rounded-lg shadow-xl overflow-hidden z-50">
                    {players.length > 0 ? (
                        <ul>
                            {players.map((player) => (
                                <li key={player.id}>
                                    <button
                                        onClick={() => handleSelect(player)}
                                        className="w-full px-4 py-3 flex items-center justify-between hover:bg-sideline transition-colors text-left"
                                    >
                                        <div>
                                            <p className="text-chalk font-medium">{player.full_name}</p>
                                        </div>
                                    </button>
                                </li>
                            ))}
                        </ul>
                    ) : !isLoading ? (
                        <div className="px-4 py-3 text-dust text-center">No players found</div>
                    ) : null}
                </div>
            )}

            {isOpen && (
                <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />
            )}
        </div>
    );
}