export function stationKey(id: string | null | undefined): string {
  // "ST30" and "ST30-WLD" are the same station; "UT-AIR" keeps both parts.
  if (!id) return "";
  const up = id.toUpperCase();
  if (up.startsWith("UT-")) return up;
  return up.split("-")[0];
}

export function humanize(s: string): string {
  return s.replace(/_/g, " ");
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().slice(11, 19) + "Z";
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().slice(0, 16).replace("T", " ") + "Z";
}

export function fmtUsd(n: number, digits = 4): string {
  return "$" + n.toFixed(digits);
}

export function fmtNum(n: number): string {
  return Math.abs(n) >= 1000 ? n.toLocaleString("en-US", { maximumFractionDigits: 0 }) : String(Math.round(n * 1000) / 1000);
}

export const SOURCE_LABEL: Record<string, string> = {
  synthetic: "SYNTHETIC",
  metropt3: "MetroPT-3",
  uci_hydraulic: "UCI Hydraulic",
  ims_bearings: "IMS Bearings",
  mimii: "MIMII",
  maintie: "MaintIE",
};

export function sourceName(id: string): string {
  return SOURCE_LABEL[id] ?? id;
}
