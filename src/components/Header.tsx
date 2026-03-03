import Link from "next/link";

export default function Header() {
    return (
        <header className="border-b border-sideline bg-hardwood/80 backdrop-blur-sm sticky top-0 z-50">
            <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
                {/* Logo */}
                <Link href="/" className="flex items-center gap-3 group">
                    <div className="w-10 h-10 bg-gold rounded-lg flex items-center justify-center group-hover:shadow-glow-sm transition-shadow">
                        <span className="font-display text-court text-xl">PRA</span>
                    </div>
                    <div>
                        <h1 className="font-display text-2xl text-chalk tracking-wide">
                            NBA PRA <span className="text-gold">PREDICTOR</span>
                        </h1>
                    </div>
                </Link>

                {/* Nav Links */}
                <nav className="hidden md:flex items-center gap-6">
                    <Link
                        href="/"
                        className="text-dust hover:text-chalk transition-colors text-sm uppercase tracking-widest"
                    >
                        Dashboard
                    </Link>
                    <Link
                        href="/players"
                        className="text-dust hover:text-chalk transition-colors text-sm uppercase tracking-widest"
                    >
                        Players
                    </Link>
                    <Link
                        href="/about"
                        className="text-dust hover:text-chalk transition-colors text-sm uppercase tracking-widest"
                    >
                        About
                    </Link>
                </nav>

                {/* Mobile menu button */}
                <button className="md:hidden text-dust hover:text-chalk">
                    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                    </svg>
                </button>
            </div>
        </header>
    );
}