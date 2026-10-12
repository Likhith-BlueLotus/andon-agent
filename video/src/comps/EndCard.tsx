import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { prog, vis } from "../lib/anim";
import { C, MONO, THEME_STRING } from "../lib/theme";
import { Badge, Stage, Tower } from "../lib/ui";
import { useFonts } from "../lib/useFonts";

export const END_FRAMES = 150;

export const EndCard: React.FC = () => {
  useFonts();
  const f = useCurrentFrame();
  const out = 1 - prog(f, END_FRAMES - 10, 10);
  const lift = (from: number) => (1 - prog(f, from, 24)) * 16;
  return (
    <AbsoluteFill style={{ opacity: out }}>
      <Stage>
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 34, textAlign: "center", padding: "0 120px" }}>
          <div style={{ opacity: vis(f, 4), display: "flex", alignItems: "center", gap: 30 }}>
            <Tower size={110} on="green" />
            <div style={{ fontSize: 100, fontWeight: 700, letterSpacing: "-0.03em" }}>Andon Agent</div>
          </div>
          <div style={{ opacity: vis(f, 14), transform: `translateY(${lift(14)}px)`, fontFamily: MONO, fontSize: 64, fontWeight: 500, color: C.accent, marginTop: 20 }}>https://andon-agent-b9c77.web.app</div>
          <div style={{ opacity: vis(f, 28), transform: `translateY(${lift(28)}px)`, fontFamily: MONO, fontSize: 46, color: C.fg }}>github.com/Likhith-BlueLotus/andon-agent</div>
          <div style={{ opacity: vis(f, 44), width: 160, height: 2, background: C.lineStrong, marginTop: 20 }} />
          <div style={{ opacity: vis(f, 48), fontSize: 36, color: C.muted, fontWeight: 500 }}>{THEME_STRING}</div>
        </div>
        <div style={{ position: "absolute", left: 0, right: 0, bottom: 130, textAlign: "center", fontSize: 30, color: C.fg, opacity: vis(f, 56) }}>No physical writes.</div>
        <Badge style={{ left: "50%", bottom: 60, transform: "translateX(-50%)", opacity: vis(f, 56) }} size={26} />
      </Stage>
    </AbsoluteFill>
  );
};
