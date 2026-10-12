import React from "react";
import { C, MONO, SANS, rgba, BADGE_TEXT } from "./theme";

export const Stage: React.FC<{ children: React.ReactNode; vertical?: boolean }> = ({ children, vertical }) => (
  <div style={{ position: "absolute", inset: 0, background: C.bg, color: C.fg, fontFamily: SANS, overflow: "hidden" }}>
    <div style={{ position: "absolute", inset: 0, backgroundImage: `linear-gradient(${rgba(C.fg, 0.035)} 1px, transparent 1px), linear-gradient(90deg, ${rgba(C.fg, 0.035)} 1px, transparent 1px)`, backgroundSize: vertical ? "60px 60px" : "80px 80px" }} />
    <div style={{ position: "absolute", inset: 0, background: "radial-gradient(ellipse at 50% 40%, rgba(168,176,255,0.07), transparent 60%)" }} />
    {children}
  </div>
);

/** The Andon tower logo from web/src/components/Brand.tsx. */
export const Tower: React.FC<{ size: number; on?: "red" | "amber" | "green" }> = ({ size, on = "red" }) => {
  const lamp = (k: string, col: string) => ({ fill: on === k ? col : rgba(col, 0.16), style: on === k ? { filter: `drop-shadow(0 0 ${size / 8}px ${col})` } : undefined });
  return (
    <svg width={size * 0.62} height={size} viewBox="0 0 14 24">
      <rect x="2" y="0.5" width="10" height="1.6" rx="0.8" fill={C.lineStrong} />
      <rect x="2.5" y="2.6" width="9" height="5" rx="1.4" {...lamp("red", C.bad)} />
      <rect x="2.5" y="8.3" width="9" height="5" rx="1.4" {...lamp("amber", C.warn)} />
      <rect x="2.5" y="14" width="9" height="5" rx="1.4" {...lamp("green", C.ok)} />
      <rect x="6" y="19.6" width="2" height="2.6" fill={C.lineStrong} />
      <rect x="3" y="22.2" width="8" height="1.6" rx="0.8" fill={C.lineStrong} />
    </svg>
  );
};

type Tone = "ok" | "bad" | "warn" | "accent" | "muted";
const tc = (t: Tone) => ({ ok: C.ok, bad: C.bad, warn: C.warn, accent: C.accent, muted: C.muted })[t];

export const IconCheck: React.FC<{ size?: number; color?: string }> = ({ size = 28, color = C.ok }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 8.5l3.2 3L13 4.5" /></svg>
);
export const IconX: React.FC<{ size?: number; color?: string }> = ({ size = 28, color = C.bad }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round"><path d="M4 4l8 8M12 4l-8 8" /></svg>
);
export const IconWarn: React.FC<{ size?: number; color?: string }> = ({ size = 28, color = C.bad }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M8 2L14.5 13.5h-13z" /><path d="M8 6.5v3.2M8 11.7v.1" /></svg>
);

/** Status is icon + word, never colour alone. */
export const Status: React.FC<{ tone: "ok" | "bad" | "warn"; text: string; size?: number }> = ({ tone, text, size = 30 }) => (
  <span style={{ display: "inline-flex", alignItems: "center", gap: size * 0.3, color: tc(tone), fontWeight: 700, fontSize: size, letterSpacing: "0.04em", fontFamily: SANS }}>
    {tone === "ok" ? <IconCheck size={size * 1.1} /> : tone === "bad" ? <IconX size={size * 1.1} /> : <IconWarn size={size * 1.1} color={C.warn} />}
    {text}
  </span>
);

export const Chip: React.FC<{ text: string; tone?: Tone; size?: number; mono?: boolean; outline?: boolean }> = ({ text, tone = "muted", size = 22, mono = true, outline = true }) => (
  <span style={{ display: "inline-flex", alignItems: "center", padding: `${size * 0.22}px ${size * 0.55}px`, borderRadius: 999, border: `1.5px solid ${rgba(tc(tone), outline ? 0.55 : 0)}`, background: rgba(tc(tone), 0.1), color: tc(tone), fontFamily: mono ? MONO : SANS, fontSize: size, fontWeight: 500, whiteSpace: "nowrap" }}>{text}</span>
);

/** Persistent honesty badge. */
export const Badge: React.FC<{ style?: React.CSSProperties; size?: number }> = ({ style, size = 22 }) => (
  <div style={{ position: "absolute", display: "inline-flex", alignItems: "center", gap: 10, padding: "8px 18px", borderRadius: 999, border: `1.5px solid ${C.lineStrong}`, background: C.sunken, color: C.muted, fontFamily: MONO, fontSize: size, fontWeight: 500, letterSpacing: "0.06em", ...style }}>
    <span style={{ width: 9, height: 9, borderRadius: 9, background: C.accent }} />
    {BADGE_TEXT}
  </div>
);

export const Eyebrow: React.FC<{ children: React.ReactNode; size?: number; color?: string }> = ({ children, size = 26, color = C.accent }) => (
  <div style={{ fontFamily: MONO, fontSize: size, letterSpacing: "0.14em", textTransform: "uppercase", color, fontWeight: 500 }}>{children}</div>
);
