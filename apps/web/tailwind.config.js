/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0a1210",
          900: "#0f1c18",
          800: "#152822",
          700: "#1c342c",
        },
        mist: {
          100: "#e8f2ee",
          200: "#c5ddd3",
          400: "#7eaea0",
        },
        signal: {
          DEFAULT: "#3dffa8",
          dim: "#1fbf7a",
          warm: "#ffb454",
        },
      },
      fontFamily: {
        display: ["var(--font-display)", "Georgia", "serif"],
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      boxShadow: {
        glow: "0 0 40px rgba(61, 255, 168, 0.12)",
      },
      keyframes: {
        rise: {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        pulseSoft: {
          "0%, 100%": { opacity: "0.45" },
          "50%": { opacity: "0.9" },
        },
        dash: {
          to: { strokeDashoffset: "-24" },
        },
      },
      animation: {
        rise: "rise 0.7s ease-out both",
        "pulse-soft": "pulseSoft 2.4s ease-in-out infinite",
        dash: "dash 1.2s linear infinite",
      },
    },
  },
  plugins: [],
};
