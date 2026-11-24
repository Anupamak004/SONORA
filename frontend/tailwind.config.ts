import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        studio: {
          bg: "#0B0D10",
          surface: "#12161C",
          elevated: "#181D25",
          border: "#232A35",
          text: "#E6EDF3",
          muted: "#8B949E",
          subtle: "#5C6673",
          amber: "#D99B26",
          cyan: "#2DD4BF",
          ok: "#34D399",
          warn: "#F59E0B",
          danger: "#F87171",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
    },
  },
  plugins: [],
} satisfies Config;
