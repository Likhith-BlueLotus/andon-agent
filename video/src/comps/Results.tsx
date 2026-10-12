import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import data from "../data.generated.json";
import { prog, vis } from "../lib/anim";
import { C, MONO, rgba } from "../lib/theme";
import { Badge, Stage } from "../lib/ui";
import { useFonts } from "../lib/useFonts";

export const RESULTS_FRAMES = 600;
const R = data.results;

// Honesty guard: this clip says "not significant". If the eval ever says otherwise, refuse to render.
if (R.sig.S_S1_vs_B1 || R.sig.R_S1_vs_B1) throw new Error("S1 vs B1 became significant; rewrite the honesty chip in Results.tsx");

// Per video/SEGMENTS.md M5: S1, B1, B2 only. S2 (no verifier) is Q&A material, not shown.
const SYS = [
  { k: "S1", name: "Andon Agent", fill: C.accent },
  { k: "B1", name: "single long prompt", fill: "rgb(140,140,140)" },
  { k: "B2", name: "classical baseline", fill: "rgb(92,92,92)" },
] as const;
type SetKey = "S" | "R";
const fmtInt = (n: number) => n.toLocaleString("en-US");
const INK2 = "rgb(72,76,82)";

const Panel: React.FC<{ f: number; at: number; set: SetKey; x: number; y: number; w: number; h: number }> = ({ f, at, set, x, y, w, h }) => {
  const n = R[set].S1.n;
  const title = set === "S" ? `S-set: synthetic line, injected truth (n = ${n})` : `R-set: real signals mapped onto the synthetic line (n = ${n})`;
  const padL = 84, padR = 24, top = 150, plotH = h - 270;
  const pw = w - padL - padR, slot = pw / 3, bw = slot * 0.4;
  const Y = (v: number) => top + plotH * (1 - v);
  return (
    <div style={{ position: "absolute", left: x, top: y, width: w, height: h, borderRadius: 22, background: C.panel, border: `1.5px solid ${C.line}`, opacity: vis(f, at) }}>
      <div style={{ position: "absolute", left: 34, right: 34, top: 22, fontSize: 26, fontWeight: 600, lineHeight: 1.2, whiteSpace: "nowrap" }}>{title}</div>
      <div style={{ position: "absolute", left: 34, top: 82, fontFamily: MONO, fontSize: 21, color: C.muted }}>top-1 root-cause accuracy [95% Wilson interval]</div>
      <svg width={w} height={h} style={{ position: "absolute", inset: 0 }}>
        {[0, 0.5, 1].map((g) => (
          <g key={g}>
            <line x1={padL} x2={w - padR} y1={Y(g)} y2={Y(g)} stroke={C.line} strokeWidth={1.5} />
            <text x={padL - 14} y={Y(g) + 8} textAnchor="end" fill={C.muted} fontFamily={MONO} fontSize={22}>{g.toFixed(1)}</text>
          </g>
        ))}
        {SYS.map((s, i) => {
          const d = R[set][s.k];
          const p = prog(f, at + 24 + i * 14, 54);
          const pw2 = prog(f, at + 24 + i * 14 + 50, 20);
          const cx = padL + slot * i + slot / 2;
          const top1 = d.top1 * p;
          return (
            <g key={s.k}>
              <rect x={cx - bw / 2} y={Y(top1)} width={bw} height={Math.max(0, Y(0) - Y(top1))} rx={6} fill={s.fill} />
              <g opacity={pw2}>
                <line x1={cx} x2={cx} y1={Y(d.lo)} y2={Y(d.hi)} stroke={C.fg} strokeWidth={3} />
                <line x1={cx - 12} x2={cx + 12} y1={Y(d.lo)} y2={Y(d.lo)} stroke={C.fg} strokeWidth={3} />
                <line x1={cx - 12} x2={cx + 12} y1={Y(d.hi)} y2={Y(d.hi)} stroke={C.fg} strokeWidth={3} />
                <text x={cx} y={Y(d.hi) - 14} textAnchor="middle" fill={C.fg} fontSize={32} fontWeight={700} fontFamily="Inter">{d.top1.toFixed(2)}</text>
              </g>
              <text x={cx} y={Y(0) + 36} textAnchor="middle" fill={C.fg} fontSize={26} fontWeight={600} fontFamily="Inter">{s.name}</text>
              <text x={cx} y={Y(0) + 68} textAnchor="middle" fill={C.muted} fontSize={23} fontFamily={MONO}>{`[${d.lo.toFixed(2)}, ${d.hi.toFixed(2)}]`}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
};

export const Results: React.FC<{ vertical?: boolean }> = ({ vertical = false }) => {
  useFonts();
  const f = useCurrentFrame();
  const s1 = R.claims.S1, b1 = R.claims.B1;
  const rate = (c: { unsupported: number; total: number }) => (100 * c.unsupported) / c.total;
  const full = Math.max(rate(s1), rate(b1));
  const cost = (R.S.S1.cost * R.S.S1.n + R.R.S1.cost * R.R.S1.n) / (R.S.S1.n + R.R.S1.n);

  const L = vertical
    ? { pw: 920, ph: 470, s: [80, 120], r: [80, 610], stat: { left: 80, top: 1095, width: 920 }, chips: 1595, chipLeft: 80, chipW: 920, headSize: 44, num: 70 }
    : { pw: 840, ph: 430, s: [100, 110], r: [980, 110], stat: { left: 100, top: 565, width: 1720 }, chips: 818, chipLeft: 100, chipW: 1720, headSize: 40, num: 78 };

  const cell = (name: string, c: { unsupported: number; total: number }, color: string, at: number) => (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 18, whiteSpace: "nowrap" }}>
        <span style={{ fontSize: L.num, fontWeight: 700, color, letterSpacing: "-0.02em", fontVariantNumeric: "tabular-nums" }}>{fmtInt(c.unsupported)} of {fmtInt(c.total)}</span>
        <span style={{ fontSize: 30, color: INK2, fontFamily: MONO }}>{rate(c).toFixed(1)}%</span>
      </div>
      <div style={{ fontSize: 28, fontWeight: 600, margin: "2px 0 10px" }}>{name}</div>
      <div style={{ height: 14, width: "100%", borderRadius: 7, background: "rgb(200,214,226)", overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${Math.max(0.8, (rate(c) / full) * 100) * prog(f, at, 40)}%`, background: color, borderRadius: 7 }} />
      </div>
    </div>
  );

  const chip = (text: string, top: number, at: number, tone: "warn" | "muted") => (
    <div style={{ position: "absolute", left: L.chipLeft, top, width: L.chipW, boxSizing: "border-box", padding: "12px 24px", borderRadius: 16, border: `1.5px solid ${rgba(tone === "warn" ? C.warn : C.lineStrong, 0.8)}`, background: tone === "warn" ? rgba(C.warn, 0.08) : C.sunken, fontSize: 25, lineHeight: 1.3, color: C.fg, opacity: vis(f, at) }}>
      {text}
    </div>
  );

  return (
    <AbsoluteFill>
      <Stage vertical={vertical}>
        <div style={{ position: "absolute", left: vertical ? 80 : 100, top: 40, fontSize: L.headSize, fontWeight: 600, opacity: vis(f, 0) }}>
          Results <span style={{ color: C.muted, fontWeight: 400, fontSize: 28 }}>· eval run {R.runId}</span>
        </div>
        <Panel f={f} at={10} set="S" x={L.s[0]} y={L.s[1]} w={L.pw} h={L.ph} />
        <Panel f={f} at={36} set="R" x={L.r[0]} y={L.r[1]} w={L.pw} h={L.ph} />

        <div style={{ position: "absolute", ...L.stat, boxSizing: "border-box", padding: "20px 40px 24px", borderRadius: 22, background: "rgb(227,245,255)", color: "rgb(28,28,28)", opacity: vis(f, 300), transform: `translateY(${(1 - prog(f, 300, 24)) * 14}px)` }}>
          <div style={{ fontSize: 28, fontWeight: 700, marginBottom: 10 }}>Unsupported claims <span style={{ fontWeight: 500, color: INK2, fontSize: 24 }}>· S-set + R-set pooled</span></div>
          <div style={{ display: "flex", flexDirection: vertical ? "column" : "row", gap: vertical ? 6 : 70 }}>
            {cell("(Andon)", s1, "rgb(79,89,214)", 320)}
            <div style={{ alignSelf: vertical ? "flex-start" : "center", fontSize: 34, fontWeight: 600, color: INK2 }}>vs</div>
            {cell("(single prompt)", b1, "rgb(110,110,110)", 350)}
          </div>
        </div>

        {chip(`Top-1 difference vs single prompt: not significant (McNemar p = ${R.sig.S_p.toFixed(3)} S, ${R.sig.R_p.toFixed(3)} R). The win is grounding.`, L.chips, 6, "warn")}
        {chip(`About $${cost.toFixed(2)} per diagnosis (measured, $/run ${R.S.S1.cost.toFixed(3)} S-set, ${R.R.S1.cost.toFixed(3)} R-set)`, L.chips + (vertical ? 112 : 76), 6, "muted")}
        <Badge style={{ left: "50%", bottom: vertical ? 40 : 28, transform: "translateX(-50%)", opacity: vis(f, 0) }} size={vertical ? 20 : 22} />
      </Stage>
    </AbsoluteFill>
  );
};
