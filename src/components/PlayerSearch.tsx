"use client";

import { useState } from "react";

// Mock data for now — will replace with API later
const MOCK_PLAYERS = [
    { id: 1, name: "LeBron James", team: "LAL", position: "SF" },
    { id: 2, name: "Stephen Curry", team: "GSW", position: "PG" },
    { id: 3, name: "Kevin Durant", team: "PHX", position: "SF" },
    { id: 4, name: "Giannis Antetokounmpo", team: "MIL", position: "PF" },
    { id: 5, name: "Luka Doncic", team: "DAL", position: "PG" },
    { id: 6, name: "Jayson Tatum", team: "BOS", position: "SF" },
    { id: 7, name: "Joel Embiid", team: "PHI", position: "C" },
    { id: 8, name: "Nikola Jokic", team: "DEN", position: "C" },
    { id: 9, name: "Anthony Edwards", team: "MIN", position: "SG" },
    { id: 10, name: "Shai Gilgeous-Alexander", team: "OKC", position: "PG" },
];

interface Player {
    id: number;
    name: string;
    team: string;
    position: string;
}

interface PlayerSearchProps {
    onSelectPlayer: (player: Player) => void;
}

export default function PlayerSearch({ onSelectPlayer }: PlayerSearchProps) {
    const [query, setQuery] = useState("");
    const [isOpen, setIsOpen] = useState(false);

    const filteredPlayers = MOCK_PLAYERS.filter((player) =>
        player.name.toLowerCase().includes(query.toLowerCase())
    );

    const handleSelect = (player: Player) => {
        onSelectPlayer(player);
        setQuery(player.name);
        setIsOpen(false);
    };

    return (
        <div className="relative w-full max-w-md">
            {/* Search Input */}
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
            </div>

            {/* Dropdown Results */}
            {isOpen && query.length > 0 && (
                <div className="absolute top-full left-0 right-0 mt-2 bg-hardwood border border-sideline rounded-lg shadow-xl overflow-hidden z-50">
                    {filteredPlayers.length > 0 ? (
                        <ul>
                            {filteredPlayers.slice(0, 5).map((player) => (
                                <li key={player.id}>
                                    <button
                                        onClick={() => handleSelect(player)}
                                        className="w-full px-4 py-3 flex items-center justify-between hover:bg-sideline transition-colors text-left"
                                    >
                                        <div>
                                            <p className="text-chalk font-medium">{player.name}</p>
                                            <p className="text-dust text-sm">
                                                {player.team} • {player.position}
                                            </p>
                                        </div>
                                        <span className="text-gold text-sm font-mono">{player.team}</span>
                                    </button>
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <div className="px-4 py-3 text-dust text-center">
                            No players found
                        </div>
                    )}
                </div>
            )}

            {/* Click outside to close */}
            {isOpen && (
                <div
                    className="fixed inset-0 z-40"
                    onClick={() => setIsOpen(false)}
                />
            )}
        </div>
    );
}