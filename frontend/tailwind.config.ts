import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        ink: "var(--ink)",
        paper: "var(--paper)",
        mist: "var(--mist)",
        line: "var(--line)",
        cobalt: "var(--cobalt)",
        ember: "var(--ember)",
        moss: "var(--moss)",
        sand: "var(--sand)",
        card: "var(--card)"
      },
      boxShadow: {
        panel: "0 12px 30px rgba(24, 27, 32, 0.08)"
      },
      borderRadius: {
        panel: "1.25rem"
      }
    }
  },
  plugins: []
};

export default config;
