import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WorkOrderPanel } from "./Rca";
import { featureEnabled } from "../lib/features";
import type { WorkOrder } from "../types/events";

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
});

const wo: WorkOrder = {
  wo_id: "WO-1",
  incident_id: "inc_1",
  asset_id: "UT-AIR",
  cause_class: "air_pressure_drop",
  parts: ["Coupling kit"],
  status: "PENDING_APPROVAL",
  steps: [
    { order: 1, text: "Lock out the compressor.", is_safety: true, citation: { doc: "compressed_air", page: 21, quote: "Lock out the compressor." } },
    { order: 2, text: "Replace the leaking coupling.", is_safety: false, citation: null },
    { order: 3, text: "Log the repair.", is_safety: false, citation: null },
  ],
};

const panel = (langEnabled: boolean) => (
  <WorkOrderPanel wo={wo} incidentId="inc_1" decision="accept" edits="" enabled passcode={null} isMock langEnabled={langEnabled} />
);

async function pick(label: string) {
  await userEvent.selectOptions(screen.getByLabelText("Work order language"), label);
}

describe("work-order language toggle", () => {
  it("is hidden when the lang flag is off", () => {
    render(panel(false));
    expect(screen.queryByLabelText("Work order language")).toBeNull();
  });

  it("flag reads /api/config.features", () => {
    expect(featureEnabled({ features: ["lang"] }, "lang")).toBe(true);
    expect(featureEnabled({ features: ["tech"] }, "lang")).toBe(false);
  });

  it("keeps the safety original verbatim as the checkbox label and boxes the translation separately", async () => {
    render(panel(true));
    await pick("हिन्दी");
    const box = await screen.findByTestId("safety-translation-1");
    expect(within(box).getByText("Translation (machine, not binding)")).toBeInTheDocument();
    expect(within(box).getByText(/Lock out the compressor\./)).toHaveAttribute("lang", "hi");
    // the checkbox is named by the original only, never the translation
    const cb = screen.getByRole("checkbox", { name: /Lock out the compressor\.$/ });
    expect(cb.closest("label")).toHaveTextContent(/Lock out the compressor\./);
    expect(cb.closest("label")).not.toHaveTextContent(/डेमो/);
    expect(box.closest("label")).toBeNull();
    expect(screen.getByTestId("lang-notice")).toHaveTextContent(/not the controlling text/);
  });

  it("shows translation as main text and the original muted for non-safety steps", async () => {
    render(panel(true));
    await pick("Bahasa Indonesia");
    const t = await screen.findByTestId("translated-2");
    expect(t).toHaveAttribute("lang", "id");
    expect(screen.getByTestId("original-2")).toHaveTextContent("Replace the leaking coupling.");
  });

  it("keeps ticks across language switches and back to the original", async () => {
    render(panel(true));
    const box = () => screen.getByRole("checkbox", { name: /Lock out the compressor/ });
    await userEvent.click(box());
    expect(box()).toBeChecked();
    await pick("தமிழ்");
    await screen.findByTestId("safety-translation-1");
    expect(box()).toBeChecked();
    await pick("Original (English)");
    expect(box()).toBeChecked();
    expect(screen.getByTestId("safety-count")).toHaveTextContent("1/1");
  });

  it("shows 'translation unavailable' with the original when translation is null", async () => {
    render(panel(true));
    await pick("Tiếng Việt"); // mock leaves the last non-safety step untranslated
    await waitFor(() => expect(screen.getByTestId("translated-2")).toBeInTheDocument());
    expect(screen.queryByTestId("translated-3")).toBeNull();
    expect(screen.getByText("Log the repair.")).toBeInTheDocument();
    expect(screen.getByText("translation unavailable")).toBeInTheDocument();
  });
});
