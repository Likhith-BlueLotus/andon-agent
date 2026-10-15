import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { DEFAULT, MAX, MIN_OPEN, RAIL, settle, useSidebarWidth } from "./useSidebarWidth";

describe("settle", () => {
  it("snaps narrow widths to the icon rail and clamps open widths", () => {
    expect(settle(40)).toBe(RAIL);
    expect(settle(149)).toBe(RAIL);
    expect(settle(160)).toBe(MIN_OPEN);
    expect(settle(260.4)).toBe(260);
    expect(settle(9999)).toBe(MAX);
    expect(settle(Number.NaN)).toBe(DEFAULT);
  });
});

afterEach(() => vi.unstubAllGlobals());

describe("useSidebarWidth", () => {
  it("collapses and restores the last open width, and moves with arrow keys", () => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) });
    const { result } = renderHook(() => useSidebarWidth());
    expect(result.current.width).toBe(DEFAULT);
    const key = (k: string) => act(() => result.current.onKey({ key: k, shiftKey: false, preventDefault() {} } as unknown as React.KeyboardEvent));
    key("ArrowRight");
    expect(result.current.width).toBe(DEFAULT + 16);
    act(() => result.current.toggle());
    expect(result.current.compact).toBe(true);
    act(() => result.current.toggle());
    expect(result.current.width).toBe(DEFAULT + 16);
    key("Home");
    expect(result.current.width).toBe(RAIL);
    key("ArrowRight");
    expect(result.current.width).toBe(MIN_OPEN);
    key("End");
    expect(result.current.width).toBe(MAX);
    expect(store.get("andon.sidebar")).toBe(String(MAX));
  });
});

it("still works when storage throws (private mode, blocked site data)", () => {
  vi.stubGlobal("localStorage", { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } });
  const { result } = renderHook(() => useSidebarWidth());
  expect(result.current.width).toBe(DEFAULT);
  act(() => result.current.toggle());
  expect(result.current.compact).toBe(true);
});

it("ends a drag on pointercancel so text selection is not left disabled", () => {
    vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => {} });
    const { result } = renderHook(() => useSidebarWidth());
    act(() => result.current.startDrag({ preventDefault() {} } as unknown as React.PointerEvent, 0));
    expect(document.body.style.userSelect).toBe("none");
    act(() => void window.dispatchEvent(new Event("pointercancel")));
    expect(result.current.dragging).toBe(false);
    expect(document.body.style.userSelect).toBe("");
});
