/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0B1210",
        surface: "#121B19",
        "surface-raised": "#17211E",
        border: "#223330",
        "text-primary": "#E8F3EE",
        "text-secondary": "#7FA396",
        signal: "#4FD1AE",
        "signal-dim": "#2E7A64",
        alarm: "#FF5A3C",
        "alarm-dim": "#7A2E20",
        warn: "#E8B84B",
      },
      fontFamily: {
        display: ["'Space Grotesk'", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      keyframes: {
        "alarm-strobe": {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(255,90,60,0.0)" },
          "15%": { boxShadow: "0 0 0 4px rgba(255,90,60,0.35)" },
          "30%": { boxShadow: "0 0 0 0 rgba(255,90,60,0.0)" },
        },
      },
      animation: {
        "alarm-strobe": "alarm-strobe 1.1s ease-out 1",
      },
    },
  },
  plugins: [],
};
