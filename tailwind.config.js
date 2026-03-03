/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        court: "#0d0d14",
        hardwood: "#13131f",
        sideline: "#1a1a2e",
        highlight: "#e94560",
        gold: "#f1c40f",
        ice: "#a8d5e5",
        chalk: "#f5f5f5",
        dust: "#8b8b9e",
        lakers: "#552583",
        celtics: "#007a33",
        heat: "#98002e",
        warriors: "#1d428a",
      },
      fontFamily: {
        display: ["Bebas Neue", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
        body: ["DM Sans", "sans-serif"],
      },
      backgroundImage: {
        "court-gradient": "linear-gradient(135deg, #0d0d14 0%, #1a1a2e 100%)",
        "card-gradient": "linear-gradient(180deg, #1a1a2e 0%, #13131f 100%)",
        "glow-gold": "radial-gradient(ellipse at center, rgba(241,196,15,0.15) 0%, transparent 70%)",
        "glow-highlight": "radial-gradient(ellipse at center, rgba(233,69,96,0.15) 0%, transparent 70%)",
      },
      boxShadow: {
        "glow-sm": "0 0 15px rgba(241,196,15,0.3)",
        "glow-md": "0 0 30px rgba(241,196,15,0.4)",
        "glow-highlight": "0 0 20px rgba(233,69,96,0.4)",
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "count-up": "countUp 1s ease-out forwards",
        "slide-up": "slideUp 0.5s ease-out forwards",
        "fade-in": "fadeIn 0.6s ease-out forwards",
      },
      keyframes: {
        countUp: {
          "0%": { opacity: "0", transform: "translateY(10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(20px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
      },
    },
  },
  plugins: [],
};