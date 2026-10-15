import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/** WCAG 2.x contrast of every text token against every surface token, in both themes. */
const css = readFileSync(resolve(__dirname, "../index.css"), "utf8");

function tokens(selector: string): Record<string, number[]> {
  const start = css.indexOf(selector);
  const block = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
  const out: Record<string, number[]> = {};
  for (const m of block.matchAll(/--([a-z0-9-]+):\s*(\d+)\s+(\d+)\s+(\d+)/g)) out[m[1]] = [Number(m[2]), Number(m[3]), Number(m[4])];
  return out;
}

function lum([r, g, b]: number[]): number {
  const c = [r, g, b].map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
const ratio = (a: number[], b: number[]) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

describe.each([
  ["dark", '[data-theme="dark"] {'],
  ["light", '[data-theme="light"] {'],
])("%s theme", (_name, sel) => {
  const t = tokens(sel);
  const surfaces = ["bg", "sunken", "panel", "raised"];
  const texts = ["fg", "muted", "accent", "ok", "warn", "bad"];
  for (const s of surfaces)
    for (const x of texts)
      it(`${x} on ${s} >= 4.5:1`, () => {
        expect(t[s], `token --${s}`).toBeDefined();
        expect(ratio(t[x], t[s])).toBeGreaterThanOrEqual(4.5);
      });
  it("accent-fg on accent >= 4.5:1 (primary button label)", () => expect(ratio(t["accent-fg"], t.accent)).toBeGreaterThanOrEqual(4.5));
  it("KPI ink on both pastel tiles >= 4.5:1", () => {
    for (const tile of ["kpi-1", "kpi-2"]) for (const ink of ["kpi-fg", "kpi-muted"]) expect(ratio(t[ink], t[tile])).toBeGreaterThanOrEqual(4.5);
  });
  it("text on frosted glass >= 4.5:1, even over the strongest ambient tint", () => {
    const num = (k: string) => Number(new RegExp(`--${k}:\\s*([\\d.]+)`).exec(css.slice(css.indexOf(sel)))![1]);
    const mix = (a: number[], b: number[], w: number) => a.map((v, i) => v * w + b[i] * (1 - w));
    for (const tint of ["c-indigo", "c-mint", "c-sky"]) {
      const page = mix(t[tint], t.bg, num("amb"));
      const glass = mix(t.glass, page, num("glass-a"));
      for (const x of ["fg", "muted", "accent"]) expect(ratio(t[x], glass), `${x} on glass over ${tint}`).toBeGreaterThanOrEqual(4.5);
      for (const x of ["fg", "muted"]) expect(ratio(t[x], page), `${x} on page over ${tint}`).toBeGreaterThanOrEqual(4.5);
    }
  });
  it("bg on fg >= 4.5:1 (primary button label)", () => expect(ratio(t.bg, t.fg)).toBeGreaterThanOrEqual(4.5));
  it("bg on ok >= 4.5:1 (approve button label)", () => expect(ratio(t.bg, t.ok)).toBeGreaterThanOrEqual(4.5));
});
