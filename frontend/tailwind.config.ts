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
        line: "hsl(206 28% 86%)",
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
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-in": "fade-in 360ms ease-out",
      },
    },
  },
  plugins: [],
};

export default config;
