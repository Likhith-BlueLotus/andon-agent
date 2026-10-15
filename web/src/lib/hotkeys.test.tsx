import { describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { useHotkeys } from "./hotkeys";

describe("useHotkeys", () => {
  it("fires once per press and ignores auto-repeat (holding `i` must not start two paid runs)", () => {
    const f = vi.fn();
    renderHook(() => useHotkeys({ i: f }));
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "i" }));
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "i", repeat: true }));
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "i", repeat: true }));
    expect(f).toHaveBeenCalledTimes(1);
  });
});
