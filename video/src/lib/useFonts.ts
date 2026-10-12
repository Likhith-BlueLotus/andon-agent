import { useEffect, useState } from "react";
import { continueRender, delayRender } from "remotion";
import "../fonts.css";

const FACES = ['400 28px "Inter"', '500 28px "Inter"', '600 28px "Inter"', '700 28px "Inter"', '400 28px "IBM Plex Mono"', '500 28px "IBM Plex Mono"', '600 28px "IBM Plex Mono"'];

/** Blocks the frame render until the bundled @fontsource fonts are decoded, so no frame ever uses a fallback. */
export function useFonts(): void {
  const [handle] = useState(() => delayRender("fonts"));
  useEffect(() => {
    Promise.all(FACES.map((f) => document.fonts.load(f, "AaBb0123 ΔST20"))).then(() => continueRender(handle));
  }, [handle]);
}
