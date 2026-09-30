"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import DataFreshness from "./DataFreshness";

const NAV_LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/players", label: "Players" },
  { href: "/compare", label: "Compare" },
  { href: "/about", label: "About" },
];

export default function Header() {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <header className="border-b border-sideline bg-hardwood/80 backdrop-blur-sm sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-3 group" onClick={() => setMenuOpen(false)}>
          <div className="w-10 h-10 bg-gold rounded-lg flex items-center justify-center group-hover:shadow-glow-sm transition-shadow">
            <span className="font-display text-court text-xl">PRA</span>
          </div>
          <h1 className="font-display text-2xl text-chalk tracking-wide">
            NBA PRA <span className="text-gold">PREDICTOR</span>
          </h1>
        </Link>

        {/* Desktop nav */}
        <nav className="hidden md:flex items-center gap-6">
          <DataFreshness />
          {NAV_LINKS.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className={`text-sm uppercase tracking-widest transition-colors ${
                pathname === href ? "text-chalk" : "text-dust hover:text-chalk"
              }`}
            >
              {label}
            </Link>
          ))}
        </nav>

        {/* Mobile menu button */}
        <button
          className="md:hidden text-dust hover:text-chalk transition-colors"
          onClick={() => setMenuOpen((o) => !o)}
          aria-label="Toggle menu"
        >
          {menuOpen ? (
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          ) : (
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          )}
        </button>
      </div>

      {/* Mobile nav dropdown */}
      {menuOpen && (
        <nav className="md:hidden border-t border-sideline bg-hardwood px-6 py-3 flex flex-col gap-1">
          {NAV_LINKS.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              onClick={() => setMenuOpen(false)}
              className={`py-2.5 text-sm uppercase tracking-widest transition-colors ${
                pathname === href ? "text-chalk" : "text-dust hover:text-chalk"
              }`}
            >
              {label}
            </Link>
          ))}
          <div className="pt-2 border-t border-sideline mt-1">
            <DataFreshness />
          </div>
        </nav>
      )}
    </header>
  );
}