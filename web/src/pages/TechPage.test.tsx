import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TechPage } from "./TechPage";
import { FIXTURE_EVENTS, MOCK_CONFIG, MOCK_SCENARIOS } from "../lib/mock";
import { reduceAll } from "../state/reducer";
import { setHandoff } from "../lib/handoff";
import type { Catalog } from "../state/useCatalog";

const catalog = (over: Partial<Catalog> = {}): Catalog => ({
  loading: false,
  error: null,
  config: MOCK_CONFIG,
  scenarios: MOCK_SCENARIOS,
  replays: [],
  sources: null,
  all: MOCK_SCENARIOS.groups.flatMap((g) => g.scenarios),
  ...over,
});

const finished = () => reduceAll(FIXTURE_EVENTS);

beforeEach(() => {
  setHandoff(null);
});
afterEach(() => {
  cleanup();
  setHandoff(null);
  window.history.replaceState({}, "", "/");
});

describe("TechPage flag", () => {
  it("shows 'Not enabled on this deployment' when the tech feature is off", () => {
    window.history.replaceState({}, "", "/tech"); // no ?mock=1, no VITE_ENABLE_STRETCH
    render(<TechPage catalog={catalog({ config: { ...MOCK_CONFIG, features: ["upload"] } })} />);
    expect(screen.getByText("Not enabled on this deployment")).toBeInTheDocument();
    expect(screen.queryByTestId("tech-page")).toBeNull();
  });

  it("is on when /api/config.features includes tech", () => {
    window.history.replaceState({}, "", "/tech");
    render(<TechPage catalog={catalog({ config: { ...MOCK_CONFIG, features: ["tech"] } })} />);
    expect(screen.getByTestId("tech-page")).toBeInTheDocument();
  });
});

describe("handoff from the console", () => {
  it("opens on the Root cause card from in-memory state, without starting a stream", () => {
    const state = finished();
    expect(state.final).not.toBeNull();
    setHandoff({ state, scenarioId: "R002", mode: "replay", passcode: null });
    window.history.replaceState({}, "", `/tech?mock=1&incident=${state.incidentId}&scenario=R002`);
    render(<TechPage catalog={catalog()} />);
    expect(screen.getByTestId("card-cause")).toBeInTheDocument();
    expect(screen.getByTestId("cause-sentence").textContent).toMatch(/at /);
    expect(screen.getByTestId("confidence").textContent).toMatch(/^\d+%$/);
    expect(screen.getByLabelText("Top verified claims").querySelectorAll("li").length).toBeLessThanOrEqual(2);
    expect(screen.getByTestId("step-label").textContent).toBe("3/5 · Root cause");
  });
});

describe("card gating", () => {
  it("cannot approve until the root cause is accepted, every safety step is ticked and a name is given", async () => {
    const u = userEvent.setup();
    const state = finished();
    setHandoff({ state, scenarioId: "R002", mode: "replay", passcode: null });
    window.history.replaceState({}, "", `/tech?mock=1&incident=${state.incidentId}`);
    render(<TechPage catalog={catalog()} />);

    expect(screen.getByTestId("next")).toBeDisabled(); // no decision yet
    await u.click(screen.getByRole("button", { name: /^Accept/ }));
    await u.click(screen.getByTestId("next"));

    const total = state.workOrder!.steps.filter((s) => s.is_safety).length;
    expect(screen.getByTestId("card-safety")).toBeInTheDocument();
    expect(screen.getByTestId("safety-count").textContent).toContain(`0 / ${total}`);
    expect(screen.getByTestId("next")).toBeDisabled();
    const boxes = within(screen.getByLabelText("Lockout and tagout steps")).getAllByRole("checkbox");
    expect(boxes).toHaveLength(total);
    for (const b of boxes.slice(0, -1)) await u.click(b);
    await u.type(screen.getByLabelText("Approver name"), "A. Tech");
    expect(screen.getByTestId("next")).toBeDisabled(); // one step still open
    await u.click(boxes[boxes.length - 1]);
    expect(screen.getByTestId("safety-count").textContent).toContain(`${total} / ${total}`);
    expect(screen.getByTestId("next")).toBeEnabled();
    await u.click(screen.getByTestId("next"));

    const approve = screen.getByRole("button", { name: /Approve & send to CMMS \(mock\)/ });
    expect(approve).toBeEnabled();
    await u.click(approve);
    expect(await screen.findByTestId("decision-banner")).toHaveTextContent(/Approved and sent to the mock CMMS/);
    expect(screen.getByTestId("card-approve").getAttribute("data-wo-status")).toBe("APPROVED");
  });

  it("Next is locked on the safety card until ticks and name are given", async () => {
    const u = userEvent.setup();
    const state = finished();
    setHandoff({ state, scenarioId: "R002", mode: "replay", passcode: null });
    window.history.replaceState({}, "", `/tech?mock=1&incident=${state.incidentId}`);
    render(<TechPage catalog={catalog()} />);
    await u.click(screen.getByRole("button", { name: /^Accept/ }));
    await act(async () => { await u.click(screen.getByTestId("next")); });
    // cannot skip forward with the Next button while locked
    expect(screen.getByTestId("next")).toBeDisabled();
    expect(screen.getByTestId("next-hint").textContent).toMatch(/Locked until/);
  });
});
