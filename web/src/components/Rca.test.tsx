import { describe, expect, it, vi } from "vitest";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ClaimRow, WorkOrderPanel } from "./Rca";
import type { Claim, ClaimVerdict, WorkOrder } from "../types/events";

const claim: Claim = {
  claim_id: "cl1",
  text: "UT-AIR header pressure fell 18% at 07:58:20",
  kind: "numeric",
  evidence_ids: ["ev_detect_change_points_1"],
  asserted_value: -18,
  asserted_ts: null,
  citation: null,
};

describe("ClaimRow", () => {
  it("renders a rejected claim struck through with the measured value visible", () => {
    const v: ClaimVerdict = { claim_id: "cl1", verdict: "fail", reason: "magnitude -14.0% vs asserted -18%", measured_value: -14 };
    render(<ClaimRow claim={claim} verdict={v} onEvidence={() => undefined} />);
    const text = screen.getByText(claim.text);
    expect(text.className).toMatch(/line-through/);
    expect(screen.getByText("rejected")).toBeInTheDocument(); // status is a word, not only a colour
    expect(screen.getByText(/measured -14/)).toBeInTheDocument();
    expect(screen.getByText(/model asserted -18/)).toBeInTheDocument();
  });

  it("keeps an unverifiable claim visible and struck through", () => {
    const v: ClaimVerdict = { claim_id: "cl1", verdict: "unverifiable", reason: "no matching evidence", measured_value: null };
    render(<ClaimRow claim={claim} verdict={v} onEvidence={() => undefined} />);
    expect(screen.getByText(claim.text).className).toMatch(/line-through/);
    expect(screen.getByText("unverifiable")).toBeInTheDocument();
  });

  it("shows pending without strike-through and verified with a tick word", () => {
    const { rerender } = render(<ClaimRow claim={claim} verdict={undefined} onEvidence={() => undefined} />);
    expect(screen.getByText("pending")).toBeInTheDocument();
    expect(screen.getByText(claim.text).className).not.toMatch(/line-through/);
    rerender(<ClaimRow claim={claim} verdict={{ claim_id: "cl1", verdict: "pass", reason: "ok", measured_value: null }} onEvidence={() => undefined} />);
    expect(screen.getByText("verified")).toBeInTheDocument();
  });

  it("renders the citation as doc · p.N with the verbatim quote", () => {
    const c = { ...claim, citation: { doc: "compressed_air", page: 15, quote: "A sustained fall in header pressure." } };
    render(<ClaimRow claim={c} verdict={undefined} onEvidence={() => undefined} />);
    expect(screen.getByText("compressed_air · p.15")).toBeInTheDocument();
    expect(screen.getByText(/“A sustained fall in header pressure\.”/)).toBeInTheDocument();
  });
});

const wo: WorkOrder = {
  wo_id: "WO-1",
  incident_id: "inc_1",
  asset_id: "UT-AIR",
  cause_class: "air_pressure_drop",
  parts: [],
  status: "PENDING_APPROVAL",
  steps: [
    { order: 1, text: "Lock out the compressor.", is_safety: true, citation: { doc: "compressed_air", page: 21, quote: "Lock out the compressor." } },
    { order: 2, text: "Verify zero energy.", is_safety: true, citation: { doc: "compressed_air", page: 21, quote: "Verify zero energy." } },
    { order: 3, text: "Replace the leaking coupling.", is_safety: false, citation: null },
  ],
};

describe("WorkOrderPanel approval gating", () => {
  it("keeps Approve disabled until the RCA is accepted, a name is given and every safety step is ticked", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<WorkOrderPanel wo={wo} incidentId="inc_1" decision={null} edits="" enabled passcode={null} isMock />);
    const approve = screen.getByRole("button", { name: /Approve & send to CMMS \(mock\)/ });
    expect(approve).toBeDisabled();
    expect(screen.getByText(/Locked until: .*accept or edit the root cause/)).toBeInTheDocument();

    rerender(<WorkOrderPanel wo={wo} incidentId="inc_1" decision="accept" edits="" enabled passcode={null} isMock />);
    await user.type(screen.getByLabelText("Approver name"), "A. Tech");
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes).toHaveLength(2);
    await user.click(boxes[0]);
    expect(approve).toBeDisabled();
    expect(screen.getByTestId("safety-count")).toHaveTextContent("1/2");
    await user.click(boxes[1]);
    expect(approve).toBeEnabled();
    // un-ticking re-locks it
    await user.click(boxes[0]);
    expect(approve).toBeDisabled();
  });

  it("is disabled when the RCA was rejected even if everything is ticked", async () => {
    const user = userEvent.setup();
    render(<WorkOrderPanel wo={wo} incidentId="inc_1" decision="reject" edits="" enabled passcode={null} isMock />);
    await user.type(screen.getByLabelText("Approver name"), "A");
    for (const b of screen.getAllByRole("checkbox")) await user.click(b);
    expect(screen.getByRole("button", { name: /Approve & send/ })).toBeDisabled();
  });

  it("marks safety steps with a LOTO label and page, and ends in an approved state", async () => {
    const user = userEvent.setup();
    render(<WorkOrderPanel wo={wo} incidentId="inc_1" decision="accept" edits="" enabled passcode={null} isMock />);
    expect(screen.getAllByText(/LOTO safety step/)).toHaveLength(2);
    expect(screen.getAllByText(/verbatim from compressed_air · p\.21/)).toHaveLength(2);
    await user.type(screen.getByLabelText("Approver name"), "A");
    for (const b of screen.getAllByRole("checkbox")) await user.click(b);
    await user.click(screen.getByRole("button", { name: /Approve & send/ }));
    const banner = await screen.findByTestId("decision-banner");
    expect(within(banner).getByText(/Approved and sent to the mock CMMS/)).toBeInTheDocument();
    await waitFor(() => expect(banner).toHaveFocus());
    expect(screen.getByTestId("decision-announcer")).toHaveTextContent(/approved and sent to the mock CMMS/);
  });

  it("surfaces a 409 from the server", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: { code: "already_decided", message: "work order is already APPROVED" } }), { status: 409, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkOrderPanel wo={wo} incidentId="inc_1" decision="accept" edits="" enabled passcode={null} isMock={false} />);
    await user.type(screen.getByLabelText("Approver name"), "A");
    for (const b of screen.getAllByRole("checkbox")) await user.click(b);
    await user.click(screen.getByRole("button", { name: /Approve & send/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/409 already_decided/);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/incidents\/inc_1\/approve$/);
    expect(JSON.parse(init.body)).toMatchObject({ decision: "approve", rca_decision: "accept", ticked_safety_steps: [1, 2], approver_name: "A" });
    vi.unstubAllGlobals();
  });
});
