export default function Home() {
  return (
    <main className="min-h-screen p-8">
      {/* Header */}
      <div className="mb-12">
        <h1 className="font-display text-6xl tracking-wide text-chalk">
          NBA PRA <span className="text-gold">PREDICTOR</span>
        </h1>
        <p className="text-dust mt-2 font-body">
          ML-powered player stat predictions
        </p>
      </div>

      {/* Test Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 max-w-4xl">
        {/* Stat Card Example */}
        <div className="bg-hardwood rounded-lg p-6 border border-sideline relative overflow-hidden">
          <div className="stripe-accent absolute inset-0 pointer-events-none" />
          <p className="text-dust text-sm uppercase tracking-widest mb-2">Points</p>
          <p className="stat-number text-5xl font-bold text-gold">28.4</p>
        </div>

        <div className="bg-hardwood rounded-lg p-6 border border-sideline relative overflow-hidden">
          <div className="stripe-accent absolute inset-0 pointer-events-none" />
          <p className="text-dust text-sm uppercase tracking-widest mb-2">Rebounds</p>
          <p className="stat-number text-5xl font-bold text-ice">8.2</p>
        </div>

        <div className="bg-hardwood rounded-lg p-6 border border-sideline relative overflow-hidden">
          <div className="stripe-accent absolute inset-0 pointer-events-none" />
          <p className="text-dust text-sm uppercase tracking-widest mb-2">Assists</p>
          <p className="stat-number text-5xl font-bold text-highlight">6.1</p>
        </div>
      </div>

      {/* Glow Card Example */}
      <div className="mt-12 max-w-md">
        <div className="glow-border bg-hardwood rounded-xl p-6 border border-gold/30">
          <p className="text-dust text-xs uppercase tracking-widest mb-1">Predicted PRA</p>
          <p className="stat-number text-4xl font-bold text-chalk">42.7</p>
          <p className="text-dust text-sm mt-2">vs Lakers • Tomorrow 7:30 PM</p>
        </div>
      </div>

      {/* Typography Test */}
      <div className="mt-12 space-y-4">
        <p className="font-display text-3xl">Display Font: Bebas Neue</p>
        <p className="font-body text-lg">Body Font: DM Sans — Clean and modern</p>
        <p className="font-mono text-lg">Mono Font: JetBrains Mono — 1234567890</p>
      </div>
    </main>
  );
}