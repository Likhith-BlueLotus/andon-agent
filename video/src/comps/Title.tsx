import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { prog, vis } from "../lib/anim";
import { C, MONO, SANS, THEME_STRING, rgba } from "../lib/theme";
import { Badge, Stage, Tower } from "../lib/ui";
import { useFonts } from "../lib/useFonts";

export const TITLE_FRAMES = 240;

/** Calm signal trace behind the title: a slow sine with a step, drawn on. */
const Trace: React.FC<{ frame: number }> = ({ frame }) => {
  const W = 1920, pts: string[] = [];
  const reveal = prog(frame, 0, 150);
  for (let x = 0; x <= W; x += 8) {
    const t = x / W;
    const step = t > 0.62 ? -38 : 0;
    const y = 930 + Math.sin(t * 22 + frame / 40) * 9 + step + Math.sin(t * 61) * 3;
    pts.push(`${x},${y.toFixed(1)}`);
  }
  return (
    <svg width={1920} height={1080} style={{ position: "absolute", inset: 0, opacity: 0.55 }}>
      <defs><clipPath id="rv"><rect x={0} y={0} width={W * reveal} height={1080} /></clipPath></defs>
      <polyline points={pts.join(" ")} fill="none" stroke={C.accent} strokeWidth={2.5} clipPath="url(#rv)" />
    </svg>
  );
};

export const Title: React.FC = () => {
  useFonts();
  const f = useCurrentFrame();
  const out = 1 - prog(f, TITLE_FRAMES - 12, 12);
  const lamp = f < 95 ? "red" : f < 160 ? "amber" : "green";
  const lift = (from: number) => (1 - prog(f, from, 24)) * 18;
  return (
    <AbsoluteFill style={{ opacity: out }}>
      <Stage>
        <Trace frame={f} />
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 36, padding: "0 140px", textAlign: "center" }}>
          <div style={{ opacity: vis(f, 10), transform: `translateY(${lift(10)}px)`, display: "flex", alignItems: "center", gap: 44 }}>
            <Tower size={170} on={lamp} />
            <div style={{ fontSize: 176, fontWeight: 700, letterSpacing: "-0.03em", lineHeight: 1 }}>Andon Agent</div>
          </div>
          <div style={{ opacity: vis(f, 45), transform: `translateY(${lift(45)}px)`, fontFamily: MONO, fontSize: 38, color: C.accent, letterSpacing: "0.02em", fontWeight: 500 }}>{THEME_STRING}</div>
          <div style={{ opacity: vis(f, 85), transform: `translateY(${lift(85)}px)`, fontSize: 48, color: C.fg, fontWeight: 500, maxWidth: 1500, lineHeight: 1.25 }}>
            Verified root cause for a stopped line, in minutes
          </div>
        </div>
        <Badge style={{ left: "50%", bottom: 50, transform: "translateX(-50%)", opacity: vis(f, 120) }} size={24} />
      </Stage>
    </AbsoluteFill>
  );
};
