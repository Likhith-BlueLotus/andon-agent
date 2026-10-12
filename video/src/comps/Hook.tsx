import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import data from "../data.generated.json";
import { easeInOut, prog, vis } from "../lib/anim";
import { C, MONO, SANS, rgba } from "../lib/theme";
import { Badge, Chip, IconCheck, IconWarn, Stage, Tower } from "../lib/ui";
import { useFonts } from "../lib/useFonts";

export const HOOK_FRAMES = 360;
const STOP_F = 45; // alarms start
const SWEEP_F = 215; // upstream sweep starts
const SWEEP_D = 55;

const STATIONS = [
  ["ST10", "Press"], ["ST20", "Weld A"], ["ST30", "Weld B"], ["ST40", "Sealer"], ["ST50", "Conveyor"], ["ST60", "Vision"],
] as const;
const ALARM = new Set(["ST20"]);
const AIR = new Set(["ST20", "ST30", "ST50"]); // illustrative feeds (the app's mimic also draws two utility rails)

type Pt = { u: number; v: number };

export const Hook: React.FC<{ vertical?: boolean }> = ({ vertical = false }) => {
  useFonts();
  const f = useCurrentFrame();
  const { width: W, height: H } = useVideoConfig();

  // ---- geometry in (u along the line, v across it); map() turns it into x,y
  const map = (p: Pt) => (vertical ? { x: p.v, y: p.u } : { x: p.u, y: p.v });
  const A = vertical ? 120 : 190; // station size along the line
  const B = vertical ? 360 : 150; // station size across the line
  const centre = (i: number) => (vertical ? 330 + i * 165 : 515 + i * 242);
  const v0 = vertical ? 540 : 440;
  const vChl = vertical ? 240 : v0 - B / 2 - 140;
  const vAir = vertical ? 840 : v0 + B / 2 + 140;
  const nodeU = vertical ? 1310 : 240; // centre of the utility nodes along u
  const nodeA = vertical ? 130 : 280; // node size along u
  const nodeB = vertical ? 300 : 120; // node size across
  const nodeEdge = vertical ? nodeU - nodeA / 2 : nodeU + nodeA / 2; // where a rail meets its node
  const farU = vertical ? centre(0) : centre(5);

  const rect = (c: Pt, a: number, b: number) => {
    const p = map({ u: c.u - a / 2, v: c.v - b / 2 }), q = map({ u: c.u + a / 2, v: c.v + b / 2 });
    return { left: Math.min(p.x, q.x), top: Math.min(p.y, q.y), width: Math.abs(q.x - p.x), height: Math.abs(q.y - p.y) };
  };
  const path = (pts: Pt[]) => pts.map((p, i) => { const m = map(p); return `${i ? "L" : "M"}${m.x} ${m.y}`; }).join(" ");

  // ---- clocks
  const running = f >= STOP_F;
  // The only number on screen is the published figure; it counts up to it, never past it.
  const shown = (data.perHour / 1e6) * prog(f, STOP_F + 6, 60);
  const pulse = 0.5 + 0.5 * Math.sin(((f - STOP_F) / 30) * Math.PI * 1.2);
  const sweep = prog(f, SWEEP_F, SWEEP_D, easeInOut);
  const arrived = sweep >= 1;

  const sweepPath = (i: number) => path([{ u: centre(i), v: v0 + B / 2 }, { u: centre(i), v: vAir }, { u: nodeEdge, v: vAir }]);

  const stationBox = (i: number) => {
    const [id, name] = STATIONS[i];
    const alarm = running && ALARM.has(id);
    const hold = running && !alarm;
    const col = alarm ? C.bad : hold ? C.muted : C.ok;
    const word = alarm ? "ALARM" : hold ? "HOLD" : "RUN";
    return (
      <div key={id} style={{ position: "absolute", ...rect({ u: centre(i), v: v0 }, A, B), boxSizing: "border-box", borderRadius: 18, background: alarm ? rgba(C.bad, 0.12 + 0.06 * pulse) : C.panel, border: `${alarm ? 3 : 1.5}px solid ${alarm ? C.bad : C.line}`, boxShadow: alarm ? `0 0 ${14 + 26 * pulse}px ${rgba(C.bad, 0.35 + 0.25 * pulse)}` : "none", padding: vertical ? "0 28px" : "0 18px", display: "flex", flexDirection: vertical ? "row" : "column", alignItems: "center", justifyContent: vertical ? "space-between" : "center", gap: 8, opacity: vis(f, 6 + i * 4) }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: vertical ? "flex-start" : "center" }}>
          <div style={{ fontFamily: MONO, fontSize: 40, fontWeight: 600 }}>{id}</div>
          <div style={{ fontSize: 24, color: C.muted }}>{name}</div>
        </div>
        <div style={{ display: "inline-flex", alignItems: "center", gap: 8, color: col, fontWeight: 700, fontSize: 28, letterSpacing: "0.06em" }}>
          {alarm ? <IconWarn size={30} color={C.bad} /> : hold ? <span style={{ fontFamily: MONO, fontSize: 26 }}>‖</span> : <IconCheck size={28} />}
          {word}
        </div>
      </div>
    );
  };

  const flowArrows = STATIONS.slice(0, 5).map((_, i) => {
    const a = centre(i) + A / 2, b = centre(i + 1) - A / 2;
    const mid = (a + b) / 2;
    return <path key={i} d={path([{ u: a + 4, v: v0 }, { u: b - 4, v: v0 }])} stroke={C.lineStrong} strokeWidth={3} fill="none" markerEnd="none" opacity={vis(f, 14 + i * 4)} />;
  });

  const rails = (
    <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
      {/* line flow */}{flowArrows}
      {/* utility rails */}
      <path d={path([{ u: nodeEdge, v: vAir }, { u: farU, v: vAir }])} stroke={C.lineStrong} strokeWidth={4} fill="none" opacity={vis(f, 20)} />
      <path d={path([{ u: nodeEdge, v: vChl }, { u: farU, v: vChl }])} stroke={C.lineStrong} strokeWidth={4} fill="none" opacity={vis(f, 24)} />
      {STATIONS.map(([id], i) => {
        const air = AIR.has(id);
        return <path key={id} d={path([{ u: centre(i), v: air ? v0 + B / 2 : v0 - B / 2 }, { u: centre(i), v: air ? vAir : vChl }])} stroke={C.lineStrong} strokeWidth={3} strokeDasharray="2 8" strokeLinecap="round" fill="none" opacity={vis(f, 26 + i * 3)} />;
      })}
      {/* upstream sweep: two comets from the alarming cells down to UT-AIR */}
      {[1].map((i) => (
        <path key={i} d={sweepPath(i)} pathLength={1} stroke={C.accent} strokeWidth={7} strokeLinecap="round" fill="none"
          strokeDasharray={`${Math.min(sweep, 0.999) * 1} 2`} opacity={vis(f, SWEEP_F, undefined, 6)} style={{ filter: `drop-shadow(0 0 8px ${C.accent})` }} />
      ))}
    </svg>
  );

  const utilNode = (id: "UT-AIR" | "UT-CHL", v: number) => (
    <div style={{ position: "absolute", ...rect({ u: nodeU, v }, nodeA, nodeB), boxSizing: "border-box", borderRadius: 16, background: C.panel, border: `1.5px solid ${C.line}`, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", opacity: vis(f, 16) }}>
      <div style={{ fontFamily: MONO, fontSize: 34, fontWeight: 600 }}>{id}</div>
      <div style={{ fontSize: 24, color: C.muted }}>{id === "UT-AIR" ? "plant air" : "chilled water"}</div>
    </div>
  );

  // ---- ticker + captions
  const tickerBox: React.CSSProperties = vertical
    ? { left: 80, top: 1405, width: W - 160 }
    : { left: 100, top: 790, width: 840 };
  const capBox: React.CSSProperties = vertical
    ? { left: 80, top: 1690, width: W - 160, height: 130, textAlign: "center" }
    : { left: 990, top: 800, width: 830, height: 200 };
  const capSize = vertical ? 56 : 62;

  const cap = (text: string, from: number, out: number | undefined, accent = false) => (
    <div style={{ position: "absolute", ...capBox, display: "flex", alignItems: "center", justifyContent: vertical ? "center" : "flex-start", opacity: vis(f, from, out), transform: `translateY(${(1 - prog(f, from, 22)) * 14}px)`, fontSize: capSize, lineHeight: 1.15, fontWeight: 700, letterSpacing: "-0.01em", textWrap: "balance" as const }}>
      {accent ? <span><span style={{ color: C.accent }}>The cause isn't</span> where the alarm is.</span> : text}
    </div>
  );

  return (
    <AbsoluteFill>
      <Stage vertical={vertical}>
        {/* header */}
        <div style={{ position: "absolute", left: vertical ? 80 : 100, top: 60, right: vertical ? 80 : 100, display: "flex", alignItems: "center", justifyContent: "space-between", opacity: vis(f, 0) }}>
          <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
            <Tower size={54} on={running ? "red" : "green"} />
            <div style={{ fontSize: 34, fontWeight: 600 }}>Line L1 <span style={{ color: C.muted, fontWeight: 400 }}>· body shop</span></div>
          </div>
          <Chip text="ILLUSTRATIVE" size={22} />
        </div>
        {rails}
        {STATIONS.map((_, i) => stationBox(i))}
        {utilNode("UT-CHL", vChl)}
        {utilNode("UT-AIR", vAir)}

        {/* stop banner */}
        <div style={{ position: "absolute", left: vertical ? 80 : 100, top: vertical ? 150 : 124, display: "inline-flex", alignItems: "center", gap: 14, color: C.bad, fontWeight: 700, fontSize: 30, letterSpacing: "0.05em", opacity: vis(f, STOP_F + 6) }}>
          <IconWarn size={34} /> LINE STOPPED
        </div>

        {/* the cited downtime figure: an assumption from a published report, labelled as one */}
        <div style={{ position: "absolute", ...tickerBox, boxSizing: "border-box", padding: "24px 32px", borderRadius: 22, background: "rgb(227,245,255)", color: "rgb(28,28,28)", opacity: vis(f, STOP_F + 4) }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 16 }}>
            <span style={{ fontSize: 26, fontWeight: 600, whiteSpace: "nowrap" }}>Large automotive plant, unplanned downtime</span>
            <span style={{ fontFamily: MONO, fontSize: 21, color: "rgb(72,76,82)", fontWeight: 500, whiteSpace: "nowrap" }}>est. · assumption</span>
          </div>
          <div>
            <div style={{ fontSize: 108, fontWeight: 700, lineHeight: 1.1, fontVariantNumeric: "tabular-nums", letterSpacing: "-0.02em", whiteSpace: "nowrap" }}>${shown.toFixed(1)}M <span style={{ fontSize: 56, fontWeight: 600 }}>/ hour</span></div>
          </div>
          <div style={{ fontSize: 24, color: "rgb(72,76,82)", lineHeight: 1.3 }}>Siemens, The True Cost of Downtime 2024, p. 2</div>
        </div>

        {cap("An alarm at ST20. The line stops.", STOP_F + 20, SWEEP_F + 12)}
        {cap("", SWEEP_F + SWEEP_D + 10, undefined, true)}
        <Badge style={vertical ? { left: "50%", bottom: 36, transform: "translateX(-50%)", opacity: vis(f, 0) } : { right: 100, bottom: 34, opacity: vis(f, 0) }} size={vertical ? 20 : 22} />
      </Stage>
    </AbsoluteFill>
  );
};
