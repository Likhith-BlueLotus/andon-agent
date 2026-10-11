/** Colours come from CSS variables (src/index.css) so the light and dark themes share one set of tokens. */
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: v("bg"),
        panel: v("panel"),
        raised: v("raised"),
        line: v("line"),
        fg: v("fg"),
        muted: v("muted"),
        accent: v("accent"),
        "accent-fg": v("accent-fg"),
        ok: v("ok"),
        warn: v("warn"),
        bad: v("bad"),
      },
      fontFamily: {
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
        sans: ['"IBM Plex Sans"', "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
      },
      keyframes: {
        stoppulse: { "0%,100%": { boxShadow: "0 0 0 0 rgb(var(--bad) / 0.55)" }, "50%": { boxShadow: "0 0 0 6px rgb(var(--bad) / 0)" } },
        spin: { to: { transform: "rotate(360deg)" } },
      },
      animation: { stoppulse: "stoppulse 1.6s ease-in-out infinite" },
    },
  },
  plugins: [],
};
