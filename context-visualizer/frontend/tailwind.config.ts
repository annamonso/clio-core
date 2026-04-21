import type { Config } from "tailwindcss";

/**
 * Semantic token-driven palette. All colors resolve to CSS variables
 * defined in src/theme/tokens.css; dark/light switch via
 * <html data-theme="...">.
 */
const rgb = (token: string) => `rgb(var(${token}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas:  rgb("--bg-canvas"),
        surface: rgb("--bg-surface"),
        elevate: rgb("--bg-elevate"),
        hover:   rgb("--bg-hover"),

        fg: {
          DEFAULT:   rgb("--fg-primary"),
          primary:   rgb("--fg-primary"),
          secondary: rgb("--fg-secondary"),
          muted:     rgb("--fg-muted"),
        },

        border: {
          DEFAULT: rgb("--border"),
          soft:    rgb("--border-soft"),
        },

        accent: {
          DEFAULT: rgb("--accent"),
          muted:   rgb("--accent-muted"),
        },

        role: {
          orchestrator: rgb("--role-orchestrator"),
          subagent:     rgb("--role-subagent"),
          tool:         rgb("--role-tool"),
          unknown:      rgb("--role-unknown"),
        },

        ok:    rgb("--ok"),
        warn:  rgb("--warn"),
        error: rgb("--error"),
      },
      borderColor: {
        DEFAULT: rgb("--border"),
      },
      keyframes: {
        "pulse-ring": {
          "0%, 100%": { opacity: "0.4", transform: "scale(1)" },
          "50%":      { opacity: "1",   transform: "scale(1.08)" },
        },
        "edge-march": {
          to: { strokeDashoffset: "-20" },
        },
      },
      animation: {
        "pulse-ring": "pulse-ring 1.2s ease-in-out infinite",
        "edge-march": "edge-march 0.9s linear infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
