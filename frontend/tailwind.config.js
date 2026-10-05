/** @type {import('tailwindcss').Config} */
// "Ember" theme: warm cream canvas, white cards, a burnt-orange gradient frame for the header and hero.
// Verdict colours (signal / alarm / warn) are tuned for AA contrast on white and cream.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#F6EDE3",
        bg: "#FBF6F0",
        surface: "#FFFFFF",
        "surface-raised": "#FFF3E6",
        border: "#EBD9C6",
        "text-primary": "#2A160B",
        "text-secondary": "#7A5A44",
        ink: "#1C1009",
        ember: "#E2600F",
        "ember-deep": "#B53D07",
        amber: "#F7A23B",
        signal: "#0E7A52",
        "signal-dim": "#8CCBAE",
        alarm: "#C0262D",
        "alarm-dim": "#EFA7A3",
        warn: "#9A5606",
      },
      fontFamily: {
        display: ["'Plus Jakarta Sans'", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      borderRadius: {
        // Every card, badge and input in the app uses rounded-sm: one token softens them all.
        sm: "0.625rem",
      },
      boxShadow: {
        frame: "0 40px 80px -40px rgba(181, 61, 7, 0.55), 0 2px 0 0 rgba(255, 255, 255, 0.25) inset",
        card: "0 1px 0 0 rgba(255, 255, 255, 0.8) inset, 0 12px 28px -22px rgba(122, 64, 20, 0.45)",
      },
      keyframes: {
        "alarm-strobe": {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(192,38,45,0.0)" },
          "15%": { boxShadow: "0 0 0 4px rgba(192,38,45,0.30)" },
          "30%": { boxShadow: "0 0 0 0 rgba(192,38,45,0.0)" },
        },
        "glow-drift": {
          "0%, 100%": { transform: "translate3d(-50%, 0, 0) scale(1)", opacity: "0.85" },
          "50%": { transform: "translate3d(-50%, 4%, 0) scale(1.08)", opacity: "1" },
        },
        "float-slow": {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-8px)" },
        },
      },
      animation: {
        "alarm-strobe": "alarm-strobe 1.1s ease-out 1",
        "glow-drift": "glow-drift 12s ease-in-out infinite",
        "float-slow": "float-slow 7s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
