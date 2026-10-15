import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { Stepper } from "./Stepper";
import type { Step } from "../lib/progress";

const steps: Step[] = [
  { id: "stop", label: "Stop", state: "done", detail: "S3" },
  { id: "plan", label: "Plan", state: "active", detail: "pending" },
];

describe("Stepper", () => {
  it("keeps the phone summary readable by assistive tech (the desktop rail is display:none there)", () => {
    const { getByTestId } = render(<Stepper steps={steps} />);
    const compact = getByTestId("stepper-compact");
    expect(compact.closest("[aria-hidden=true]")).toBeNull();
    expect(compact.textContent).toContain("Step 2/2");
  });
});
