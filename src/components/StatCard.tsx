interface StatCardProps {
    label: string;
    value: number;
    color?: "gold" | "ice" | "highlight" | "chalk";
    size?: "sm" | "md" | "lg";
}

export default function StatCard({
    label,
    value,
    color = "chalk",
    size = "md"
}: StatCardProps) {
    const colorClasses = {
        gold: "text-gold",
        ice: "text-ice",
        highlight: "text-highlight",
        chalk: "text-chalk",
    };

    const sizeClasses = {
        sm: "text-3xl",
        md: "text-5xl",
        lg: "text-6xl",
    };

    return (
        <div className="bg-hardwood rounded-lg p-6 border border-sideline relative overflow-hidden group hover:border-gold/30 transition-colors">
            {/* Stripe accent */}
            <div className="stripe-accent absolute inset-0 pointer-events-none opacity-50 group-hover:opacity-100 transition-opacity" />

            {/* Content */}
            <div className="relative">
                <p className="text-dust text-sm uppercase tracking-widest mb-2">
                    {label}
                </p>
                <p className={`stat-number font-bold ${colorClasses[color]} ${sizeClasses[size]}`}>
                    {value.toFixed(1)}
                </p>
            </div>
        </div>
    );
}