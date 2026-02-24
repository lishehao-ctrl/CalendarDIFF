import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    container: {
      center: true,
      padding: "1rem",
      screens: {
        "2xl": "1440px",
      },
    },
    extend: {
      borderRadius: {
        xl: "1rem",
        "2xl": "1.25rem",
      },
      colors: {
        bg: "hsl(205 38% 98%)",
        surface: "hsl(0 0% 100%)",
        surface2: "hsl(205 36% 96%)",
        surface3: "hsl(204 32% 93%)",
        line: "hsl(206 28% 86%)",
        lineStrong: "hsl(205 22% 76%)",
        ink: "hsl(213 36% 14%)",
        muted: "hsl(214 14% 44%)",
        accent: "hsl(192 90% 34%)",
        accent2: "hsl(22 89% 51%)",
        success: "hsl(146 65% 38%)",
        danger: "hsl(0 76% 44%)",
        warning: "hsl(36 92% 48%)",
      },
      boxShadow: {
        card: "0 10px 26px -18px rgba(17, 39, 58, 0.35)",
        elevated: "0 16px 30px -20px rgba(14, 33, 52, 0.42)",
      },
      keyframes: {
        "enter-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "stagger-fade": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "enter-up": "enter-up 240ms cubic-bezier(0.16, 1, 0.3, 1)",
        "stagger-fade": "stagger-fade 320ms ease-out both",
      },
      transitionDuration: {
        120: "120ms",
        180: "180ms",
        240: "240ms",
      },
    },
  },
  plugins: [],
};

export default config;
