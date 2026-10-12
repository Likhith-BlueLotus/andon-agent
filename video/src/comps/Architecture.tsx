import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { prog, vis } from "../lib/anim";
import { C, MONO, SANS, rgba } from "../lib/theme";
import { Badge, Chip, IconCheck, Stage } from "../lib/ui";
import { useFonts } from "../lib/useFonts";

export const ARCH_FRAMES = 600;

type Kind = "agent" | "code" | "human" | "store";
const KC: Record<Kind, string> = { agent: C.accent, code: C.fg, human: C.warn, store: C.lineStrong };

const Node: React.FC<{ f: number; at: number; x: number; y: number; w: number; h: number; kind: Kind; title: string; sub?: string; model?: string; inline?: boolean; children?: React.ReactNode }> = ({ f, at, x, y, w, h, kind, title, sub, model, inline, children }) => (
  <div style={{ position: "absolute", left: x, top: y, width: w, height: h, boxSizing: "border-box", borderRadius: 18, background: C.panel, border: `2px solid ${kind === "store" ? C.line : rgba(KC[kind], 0.7)}`, padding: "18px 22px", opacity: vis(f, at), transform: `translateY(${(1 - prog(f, at, 24)) * 14}px)`, display: "flex", flexDirection: "column", gap: 8 }}>
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
      <div style={{ fontSize: 30, fontWeight: 700, lineHeight: 1.15 }}>{title}</div>
      {inline && model && <Chip text={model} tone="accent" size={20} />}
    </div>
    {sub && <div style={{ fontSize: 23, color: C.muted, lineHeight: 1.25 }}>{sub}</div>}
    {!inline && model && <div><Chip text={model} tone="accent" size={20} /></div>}
    {children}
  </div>
);

const Arrow: React.FC<{ f: number; at: number; d: string; dur?: number; dashed?: boolean; color?: string }> = ({ f, at, d, dur = 24, dashed, color = C.muted }) => {
  const p = prog(f, at, dur);
  return (
    <g opacity={p > 0 ? 1 : 0}>
      <path d={d} fill="none" stroke={color} strokeWidth={3.5} strokeLinejoin="round" pathLength={1} strokeDasharray={dashed ? undefined : `${p} 2`} strokeLinecap="round" opacity={dashed ? p : 1} />
      {p > 0.98 && <Head d={d} color={color} />}
    </g>
  );
};
/** Arrowhead at the end of an axis-aligned last segment. */
const Head: React.FC<{ d: string; color: string }> = ({ d, color }) => {
  const n = d.match(/-?\d+(\.\d+)?/g)!.map(Number);
  const [x, y, px, py] = [n[n.length - 2], n[n.length - 1], n[n.length - 4], n[n.length - 3]];
  const dx = Math.sign(x - px), dy = Math.sign(y - py);
  const s = 11;
  const pts = dx !== 0 ? `${x},${y} ${x - dx * s * 1.6},${y - s} ${x - dx * s * 1.6},${y + s}` : `${x},${y} ${x - s},${y - dy * s * 1.6} ${x + s},${y - dy * s * 1.6}`;
  return <polygon points={pts} fill={color} />;
};

const Tool: React.FC<{ f: number; at: number; text: string; note?: string }> = ({ f, at, text, note }) => (
  <span style={{ opacity: vis(f, at), transform: `translateY(${(1 - prog(f, at, 18)) * 8}px)`, display: "inline-flex", alignItems: "center", gap: 8, padding: "7px 12px", borderRadius: 10, background: C.sunken, border: `1.5px solid ${C.line}`, fontFamily: MONO, fontSize: 21, whiteSpace: "nowrap" }}>
    {text}{note && <span style={{ color: C.accent }}>{note}</span>}
  </span>
);

export const Architecture: React.FC = () => {
  useFonts();
  const f = useCurrentFrame();
  const cloud = ["Cloud Run", "Firebase Hosting", "BigQuery", "Firestore", "Cloud Storage", "Secret Manager"];
  return (
    <AbsoluteFill>
      <Stage>
        <div style={{ position: "absolute", left: 100, right: 100, top: 44, display: "flex", justifyContent: "space-between", alignItems: "center", opacity: vis(f, 0) }}>
          <div style={{ fontSize: 40, fontWeight: 600 }}>How a verified answer is built</div>
          <div style={{ display: "flex", gap: 12 }}>
            <Chip text="LLM agent" tone="accent" size={22} mono={false} />
            <Chip text="deterministic code" size={22} mono={false} />
            <Chip text="human" tone="warn" size={22} mono={false} />
          </div>
        </div>

        <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
          <Arrow f={f} at={60} d="M394 345 L456 345" dur={16} />
          <Arrow f={f} at={190} d="M1124 345 L1166 345" dur={16} />
          <Arrow f={f} at={235} d="M1464 345 L1516 345" dur={16} />
          <Arrow f={f} at={290} d="M1590 464 L1590 520 L1320 520 L1320 466" dur={34} color={C.bad} />
          <Arrow f={f} at={340} d="M1760 464 L1760 620 L310 620 L310 656" dur={50} color={C.ok} />
          <Arrow f={f} at={410} d="M524 740 L596 740" dur={16} />
          <Arrow f={f} at={455} d="M1040 740 L1112 740" dur={16} />
          <rect x={464} y={118} width={656} height={480} rx={22} fill="none" stroke={C.lineStrong} strokeWidth={2} strokeDasharray="8 10" opacity={vis(f, 70)} />
        </svg>
        <div style={{ position: "absolute", left: 488, top: 88, padding: "0 12px", background: C.bg, fontFamily: MONO, fontSize: 21, color: C.muted, letterSpacing: "0.12em", opacity: vis(f, 74) }}>RUN IN PARALLEL</div>

        <Node f={f} at={20} x={100} y={230} w={294} h={230} kind="agent" title="Incident Commander" sub="reads the stop, plans the checks" model="Gemini 3.8 Flash" />

        <Node f={f} at={85} x={484} y={140} w={616} h={196} kind="agent" title="Signal Analyst" model="Gemini 3.8 Flash" inline>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <Tool f={f} at={115} text="detect_change_points" />
            <Tool f={f} at={128} text="spectrum" />
            <Tool f={f} at={141} text="listen" note=" (audio)" />
          </div>
        </Node>
        <Node f={f} at={100} x={484} y={348} w={616} h={238} kind="agent" title="Evidence Librarian" model="Gemini 3.8 Flash + 3.1 Flash-Lite">
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <Tool f={f} at={154} text="search_alarms" note=" (SQL)" />
            <Tool f={f} at={167} text="cite_manual" note=" (context cache)" />
          </div>
        </Node>

        <Node f={f} at={205} x={1170} y={230} w={294} h={230} kind="agent" title="RCA Judge" sub="ranks causes, cites evidence IDs" model="Gemini 3.8 Flash" />
        <Node f={f} at={245} x={1520} y={230} w={300} h={230} kind="code" title="Deterministic Verifier" sub="code, no LLM · re-runs every claim" />
        <div style={{ position: "absolute", left: 1180, top: 532, fontSize: 25, fontWeight: 600, color: C.bad, opacity: vis(f, 310), display: "flex", gap: 10, alignItems: "center" }}>
          FAIL: rejected claims go back · max 3 loops
        </div>
        <div style={{ position: "absolute", left: 1630, top: 570, fontSize: 28, fontWeight: 700, color: C.ok, opacity: vis(f, 372), display: "inline-flex", alignItems: "center", gap: 8 }}><IconCheck size={30} />PASS</div>

        <Node f={f} at={375} x={100} y={660} w={424} h={170} kind="agent" title="Action Drafter" sub="LOTO steps quoted verbatim from the manual" model="Gemini 3.8 Flash" />
        <Node f={f} at={420} x={600} y={660} w={440} h={170} kind="human" title="Human approval" sub="technician reviews the LOTO checklist, then approves" />
        <Node f={f} at={465} x={1116} y={660} w={420} h={170} kind="store" title="Mock CMMS" sub="Firestore · PENDING_APPROVAL, until a human approves" />
        <div style={{ position: "absolute", left: 1560, top: 660, width: 260, height: 170, boxSizing: "border-box", borderRadius: 18, border: `2px solid ${C.ok}`, background: rgba(C.ok, 0.08), display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 6, textAlign: "center", opacity: vis(f, 525) }}>
          <div style={{ color: C.ok, fontWeight: 700, fontSize: 24, letterSpacing: "0.03em", lineHeight: 1.2 }}>NO PHYSICAL WRITES</div>
          <div style={{ color: C.fg, fontSize: 21, lineHeight: 1.3 }}>No PLC / SCADA.<br />One write tool:</div>
          <div style={{ color: C.ok, fontFamily: MONO, fontSize: 21 }}>draft_work_order</div>
        </div>

        <div style={{ position: "absolute", left: 100, right: 100, top: 880, display: "flex", alignItems: "center", gap: 14, opacity: vis(f, 500) }}>
          <span style={{ fontFamily: MONO, fontSize: 22, letterSpacing: "0.12em", color: C.muted, marginRight: 8 }}>GOOGLE CLOUD</span>
          {cloud.map((c, i) => <span key={c} style={{ opacity: vis(f, 500 + i * 6) }}><Chip text={c} size={24} mono={false} /></span>)}
        </div>
        <Badge style={{ left: "50%", bottom: 36, transform: "translateX(-50%)", opacity: vis(f, 0) }} />
      </Stage>
    </AbsoluteFill>
  );
};
