export default function AboutPage() {
  return (
    <main className="max-w-3xl mx-auto px-6 py-12">
      <h2 className="font-display text-4xl text-chalk mb-2">About</h2>
      <p className="text-dust mb-10">How the PRA Predictor works.</p>

      <div className="space-y-8">
        <section className="bg-hardwood border border-sideline rounded-xl p-6">
          <h3 className="font-display text-xl text-gold mb-3">The Model</h3>
          <p className="text-chalk/80 text-sm leading-relaxed">
            Points, rebounds and assists each get their own XGBoost model, trained on four seasons of NBA
            game logs. Every number is a genuine forecast rather than a share of a single total, and the
            PRA figure is simply the three added together — so the headline always matches the three
            numbers beside it. Each projection is shown with the model&apos;s typical error for that stat:
            about ±4.5 points, ±1.9 rebounds and ±1.3 assists. When the gap to your line is smaller than
            that, the pick is close to a coin flip, and the analyzer says so.
          </p>
        </section>

        <section className="bg-hardwood border border-sideline rounded-xl p-6">
          <h3 className="font-display text-xl text-gold mb-3">Features Used</h3>
          <ul className="text-chalk/80 text-sm space-y-2">
            {[
              ["Rolling averages", "L3, L5, L10 game windows for PTS, REB, AST, and PRA"],
              ["Variability", "Standard deviation of PRA over last 5 games"],
              ["Rest", "Days since the player's last game"],
              ["Back-to-back", "Whether this is the second game in two nights"],
              ["Win streak", "Rolling wins over last 5 games"],
              ["Home/away", "Home court indicator"],
              ["Teammates out", "Minutes belonging to rotation players ruled out — usage has to go somewhere"],
              ["Opponent strength", "Points, rebounds and assists the opponent has been allowing, plus pace"],
            ].map(([name, desc]) => (
              <li key={name} className="flex gap-3">
                <span className="text-gold font-mono font-bold shrink-0">{name}</span>
                <span className="text-dust">{desc}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="bg-hardwood border border-sideline rounded-xl p-6">
          <h3 className="font-display text-xl text-gold mb-3">Training Data</h3>
          <p className="text-chalk/80 text-sm leading-relaxed">
            The model is trained on roughly 110,000 player-games from the 2022-23 through 2025-26 NBA
            seasons, covering every player with at least 20 games — about 700 players, not a hand-picked
            sample. The train/validation/test split is chronological across the whole league at 70/15/15,
            so the model is only ever evaluated on games that happen after the ones it learned from.
            On held-out data the combined PRA error is about 5.9, against 6.4 for simply predicting a
            player&apos;s last-5-game average.
          </p>
        </section>

        <section className="bg-hardwood border border-sideline rounded-xl p-6">
          <h3 className="font-display text-xl text-gold mb-3">Where the Data Comes From</h3>
          <p className="text-chalk/80 text-sm leading-relaxed">
            Box scores come from the free sportsdataverse bulk dataset, with schedules and injury
            reports from ESPN&apos;s public feeds. One caveat worth stating plainly: the model learned
            &quot;teammates out&quot; from who actually played, but before tip-off that has to be inferred
            from the injury report, which is a noisier signal. Expect that feature to help less in
            practice than it did in testing. A scheduled job rebuilds the whole dataset once a day
            and precomputes every prediction, so the site itself makes no live calls to any stats
            provider. That means results are as of the last refresh rather than live — last night&apos;s
            games land the following morning.
          </p>
        </section>

        <section className="bg-hardwood border border-sideline rounded-xl p-6">
          <h3 className="font-display text-xl text-gold mb-3">Prop Line Analyzer</h3>
          <p className="text-chalk/80 text-sm leading-relaxed">
            The analyzer compares the model&apos;s projection against a sportsbook-style line you set.
            Hit rate is calculated from the player&apos;s last 20 games. Context bullets highlight
            factors that are pushing the prediction up or down relative to season averages.
          </p>
        </section>

        <section className="bg-hardwood border border-sideline rounded-xl p-6">
          <h3 className="font-display text-xl text-gold mb-3">Disclaimer</h3>
          <p className="text-chalk/80 text-sm leading-relaxed">
            This tool is for informational and educational purposes only. Predictions are based on
            historical averages and machine learning estimates — they are not guarantees of future
            performance. Always gamble responsibly.
          </p>
        </section>
      </div>
    </main>
  );
}
