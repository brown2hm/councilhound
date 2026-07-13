import type { Config } from "tailwindcss";

// Tokens from DESIGN.md / the redesign handoff (frontend/DESIGN-HANDOFF.md)
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#fffaf0",
        soft: "#faf5e8",
        card: "#f5f0e0",
        strong: "#ebe6d6",
        ink: "#0a0a0a",
        "ink-active": "#1f1f1f",
        "body-strong": "#1a1a1a",
        body: "#3a3a3a",
        muted: "#6a6a6a",
        "muted-soft": "#9a9a9a",
        hairline: "#e5e5e5",
        "hairline-soft": "#f0f0f0",
        teal: "#1a3a3a",
        mint: "#a4d4c5",
        ochre: "#e8b94a",
        // status tints (derived from the brand palette)
        "tint-ochre": "#f7e5b8",
        "tint-ochre-text": "#5c4708",
        "tint-lavender": "#e3daf8",
        "tint-lavender-text": "#3d2c73",
        "tint-mint": "#cfe8de",
        "tint-mint-text": "#14453a",
        "tint-coral": "#ffd3cd",
        "tint-coral-text": "#7a1f14",
        callout: "#faf3dd",
      },
    },
  },
  plugins: [],
};
export default config;
