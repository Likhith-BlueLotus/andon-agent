import { Easing, interpolate } from "remotion";

export const ease = Easing.bezier(0.22, 1, 0.36, 1);
export const easeInOut = Easing.bezier(0.45, 0, 0.55, 1);

/** 0 -> 1 between frames [from, from+dur], eased. Calm: no overshoot. */
export const prog = (frame: number, from: number, dur: number, e = ease) =>
  interpolate(frame, [from, from + dur], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: e });

/** Fade in at `from`, optionally fade out at `out`. */
export const vis = (frame: number, from: number, out?: number, dur = 14) =>
  prog(frame, from, dur) * (out === undefined ? 1 : 1 - prog(frame, out, dur));

export const sec = (s: number) => Math.round(s * 30);
