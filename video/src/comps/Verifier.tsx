import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import data from "../data.generated.json";
import { prog, vis } from "../lib/anim";
import { C, MONO, rgba } from "../lib/theme";
import { Badge, Chip, IconCheck, IconX, Stage } from "../lib/ui";
import { useFonts } from "../lib/useFonts";

export const VERIFIER_FRAMES = 360;
const V = data.verifier;
// Beats follow video/SEGMENTS.md M3: 0-3 s claim, 3-7 s re-run + count-up, 7-10 s rejected, 10-12 s revised + PASS.
const T_CODE = 90, T_COUNT = 150, T_REJECT = 210, T_REVISE = 300;

const num = (n: number) => (n < 0 ? "-" : "+") + Math.abs(n).toLocaleString("en-US");
const claimTs = V.rejected.text.match(/\d{4}-\d\d-\d\dT[\d:]+Z/g) ?? [];
const okRef = V.revised.reason.match(/(ev_[a-z_0-9]+):([^ ]+) \(/);
/** Keeps ISO timestamps on one line. */
const nb = (t: string) => t.split(/(\d{4}-\d\d-\d\dT[\d:]+Z)/).map((x, i) => (i % 2 ? <span key={i} style={{ whiteSpace: "nowrap" }}>{x}</span> : x));
const typed = (s: string, f: number, from: number, cps = 2.8) => s.slice(0, Math.max(0, Math.floor((f - from) * cps)));

type Line = { text: string; from: number; color?: string; bold?: boolean };
const Panel: React.FC<{ f: number; at: number; lines: Line[]; cps?: number; children?: React.ReactNode }> = ({ f, at, lines, cps, children }) => (
  <div style={{ position: "absolute", left: 990, top: 190, width: 830, height: 520, borderRadius: 20, background: C.sunken, border: `1.5px solid ${C.line}`, opacity: vis(f, at), overflow: "hidden" }}>
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "16px 24px", borderBottom: `1.5px solid ${C.line}`, background: C.panel, fontFamily: MONO, fontSize: 22, color: C.muted }}>
      <span style={{ width: 10, height: 10, borderRadius: 10, background: C.accent }} />Verifier (code, no LLM)
    </div>
    <div style={{ padding: "22px 28px", fontFamily: MONO, fontSize: 26, lineHeight: 1.6 }}>
      {lines.map((l, i) => (
        <div key={i} style={{ color: l.color ?? C.fg, fontWeight: l.bold ? 600 : 400, whiteSpace: "pre", minHeight: 42 }}>{typed(l.text, f, l.from, cps)}</div>
      ))}
      {children}
    </div>
  </div>
);

const Card: React.FC<{ f: number; at: number; label: string; text: string; asserted: string; tone: "plain" | "bad" | "ok"; struck?: boolean }> = ({ f, at, label, text, asserted, tone, struck }) => (
  <div style={{ position: "absolute", left: 100, top: 190, width: 830, height: 520, borderRadius: 20, background: C.panel, border: `${tone === "plain" ? 1.5 : 3}px solid ${tone === "bad" ? C.bad : tone === "ok" ? C.ok : C.line}`, opacity: vis(f, at), transform: `translateY(${(1 - prog(f, at, 24)) * 16}px)`, padding: "26px 34px", boxSizing: "border-box" }}>
    <Chip text={label} tone={tone === "ok" ? "ok" : "accent"} size={22} />
    <div style={{ marginTop: 22, fontSize: 38, lineHeight: 1.36, fontWeight: 500, color: struck ? C.muted : C.fg }}>
      <span style={{ textDecoration: struck ? "line-through" : "none", textDecorationColor: C.bad, textDecorationThickness: 3 }}>{nb(text)}</span>
    </div>
    <div style={{ position: "absolute", left: 34, right: 34, bottom: 26 }}>
      <div style={{ fontFamily: MONO, fontSize: 22, color: C.muted, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>asserted</div>
      <div style={{ fontFamily: MONO, fontSize: 24, lineHeight: 1.45, whiteSpace: "pre" }}>{asserted}</div>
    </div>
  </div>
);

const Stamp: React.FC<{ p: number; ok?: boolean; text: string }> = ({ p, ok, text }) => (
  <div style={{ position: "absolute", left: 100 + 830 - (ok ? 220 : 450), top: 190 - 30, opacity: p, transform: `scale(${0.92 + 0.08 * p})`, background: C.bg, borderRadius: 14, padding: "6px 18px", border: `3px solid ${ok ? C.ok : C.bad}` }}>
    <span style={{ display: "inline-flex", alignItems: "center", gap: 12, color: ok ? C.ok : C.bad, fontWeight: 700, fontSize: 38, letterSpacing: "0.04em" }}>{ok ? <IconCheck size={42} /> : <IconX size={42} />}{text}</span>
  </div>
);

export const Verifier: React.FC = () => {
  useFonts();
  const f = useCurrentFrame();
  const phase2 = f >= T_REVISE;
  const out1 = 1 - prog(f, T_REVISE - 6, 8);
  const meas = V.rejected.measured, tsM = V.rejected.tsMeasured, tsR = V.rejected.tsRoot;
  const counted = Math.round(meas * prog(f, T_COUNT, 50));

  const l1: Line[] = [
    { text: `$ re-run ${V.rejected.evRoot?.ev}`, from: T_CODE + 8, color: C.accent },
    { text: `  ST40-SLR onset  ${tsR}`, from: T_CODE + 24, color: C.muted },
    { text: `$ re-run ${V.rejected.evMeasured?.ev}`, from: T_CODE + 40, color: C.accent },
    { text: `  ST60-VIS onset  ${tsM}`, from: T_CODE + 56, color: C.muted },
  ];
  const l2: Line[] = [
    { text: `$ re-run ${okRef?.[1]}`, from: T_REVISE + 8, color: C.accent },
    { text: `  ${okRef?.[2]}  ${V.revised.assertedTs}`, from: T_REVISE + 18, color: C.muted },
  ];
  const stamp1 = prog(f, T_REJECT, 14);
  const stamp2 = prog(f, T_REVISE + 24, 14);

  return (
    <AbsoluteFill>
      <Stage>
        <div style={{ position: "absolute", left: 100, right: 100, top: 56, display: "flex", justifyContent: "space-between", alignItems: "center", opacity: vis(f, 0) }}>
          <div style={{ fontSize: 38, fontWeight: 600 }}>Deterministic Verifier</div>
          <Chip text={`Iteration ${phase2 ? V.iter2 : V.iter1} of ${V.maxIter}`} tone="accent" size={26} />
        </div>

        <div style={{ opacity: out1 }}>
          <Card f={f} at={6} tone={stamp1 > 0 ? "bad" : "plain"} label={`Judge claim (${V.rejected.kind.replace("_", " ")})`} text={V.rejected.text} struck={stamp1 > 0}
            asserted={`ST40-SLR onset  ${claimTs[0] ?? ""}\nST60-VIS onset  ${claimTs[1] ?? ""}\n=> ST40-SLR (the cause) is first`} />
          <Panel f={f} at={T_CODE} lines={l1}>
            <div style={{ opacity: vis(f, T_COUNT), color: stamp1 > 0 ? C.bad : C.fg, fontWeight: 700, fontSize: 40, marginTop: 14, fontVariantNumeric: "tabular-nums" }}>
              measured {num(counted)} s
            </div>
            <div style={{ opacity: vis(f, T_REJECT + 12), color: C.bad, fontSize: 24, lineHeight: 1.4, marginTop: 12, whiteSpace: "normal", fontFamily: MONO }}>
              ST60-VIS onset {tsM} is {Math.abs(meas)} s before root ST40-SLR onset {tsR}
            </div>
          </Panel>
          <Stamp p={stamp1} text="REJECTED: reversed" />
        </div>

        {phase2 && (
          <div>
            <Card f={f} at={T_REVISE} tone={stamp2 > 0 ? "ok" : "plain"} label="Revised claim" text={`ST60-VIS reject onset ${V.revised.assertedTs} \u2192 verified (+0 s)`}
              asserted={`ts  ${V.revised.assertedTs}`} />
            <Panel f={f} at={T_REVISE} lines={l2} cps={4}>
              <div style={{ opacity: vis(f, T_REVISE + 24), color: C.ok, fontWeight: 700, fontSize: 40, marginTop: 14 }}>measured {num(V.revised.measured)} s</div>
              <div style={{ opacity: vis(f, T_REVISE + 32), color: C.ok, fontSize: 28, marginTop: 10, fontFamily: MONO }}>verified ({num(V.revised.measured)} s)</div>
            </Panel>
            <Stamp p={stamp2} ok text="PASS" />
            <div style={{ position: "absolute", left: 100, right: 100, top: 732, textAlign: "center", opacity: vis(f, T_REVISE + 30), color: C.ok, fontWeight: 700, fontSize: 32, display: "flex", justifyContent: "center", alignItems: "center", gap: 12 }}><IconCheck size={34} />Iteration {V.iter2} of {V.maxIter}: PASS</div>
          </div>
        )}

        <div style={{ position: "absolute", left: 100, right: 100, top: 800, textAlign: "center", fontSize: 50, fontWeight: 700, letterSpacing: "-0.01em", opacity: vis(f, 20), lineHeight: 1.2 }}>
          Code checks every number. <span style={{ color: C.accent }}>The model never grades itself.</span>
        </div>
        <div style={{ position: "absolute", left: 100, right: 100, top: 900, textAlign: "center", fontSize: 24, color: C.muted, opacity: vis(f, 20) }}>
          Recorded run s014-cloud-1, synthetic scenario S014
        </div>
        <Badge style={{ left: "50%", bottom: 36, transform: "translateX(-50%)", opacity: vis(f, 0) }} />
      </Stage>
    </AbsoluteFill>
  );
};
