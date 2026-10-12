import data from "../data.generated.json";

/** Dark-theme tokens copied from web/src/index.css so the clips look like the product. */
export const C = {
  bg: "rgb(28,28,28)",
  sunken: "rgb(33,33,33)",
  panel: "rgb(40,40,40)",
  raised: "rgb(52,52,52)",
  line: "rgb(58,58,58)",
  lineStrong: "rgb(84,84,84)",
  fg: "rgb(250,250,250)",
  muted: "rgb(166,166,166)",
  accent: "rgb(168,176,255)", // agent activity only
  ok: "rgb(113,221,140)",
  warn: "rgb(255,197,85)",
  bad: "rgb(255,120,120)",
};
export const rgba = (rgb: string, a: number) => rgb.replace("rgb(", "rgba(").replace(")", `,${a})`);

export const SANS = '"Inter", system-ui, sans-serif';
export const MONO = '"IBM Plex Mono", ui-monospace, Menlo, monospace';

export const THEME_STRING = data.theme;
export const BADGE_TEXT = data.badge;
