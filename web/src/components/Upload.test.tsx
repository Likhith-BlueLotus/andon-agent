import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ProvenanceChip } from "./ui";
import { UploadPage } from "../pages/UploadPage";
import { Console } from "./Console";
import { setPasscode } from "../lib/passcode";
import { MOCK_CONFIG, MOCK_SCENARIOS, MOCK_REPLAYS, MOCK_SOURCES } from "../lib/mock";
import type { Catalog } from "../state/useCatalog";

const catalog: Catalog = { loading: false, error: null, config: MOCK_CONFIG, scenarios: MOCK_SCENARIOS, replays: MOCK_REPLAYS, sources: MOCK_SOURCES, all: MOCK_SCENARIOS.groups.flatMap((g) => g.scenarios) };

beforeEach(() => {
  setPasscode(null);
  window.history.replaceState({}, "", "/");
});

describe("USER UPLOAD provenance chip", () => {
  it("reads USER UPLOAD, has its own style, and shows source_ref in the tooltip", async () => {
    render(<ProvenanceChip provenance={[{ source_id: "user_upload", real: false, source_ref: "upload_air_leak.csv col Compressor_Amps" }]} />);
    const chip = screen.getByText("USER UPLOAD");
    expect(chip).toHaveAttribute("data-provenance", "upload");
    await userEvent.tab();
    expect(await screen.findByRole("tooltip")).toHaveTextContent("upload_air_leak.csv col Compressor_Amps");
  });
  it("leaves REAL and SYNTHETIC alone", () => {
    render(<ProvenanceChip provenance={[{ source_id: "metropt3", real: true, source_ref: null }, { source_id: "synthetic", real: false, source_ref: null }]} />);
    expect(screen.getByText("REAL · MetroPT-3")).toHaveAttribute("data-provenance", "real");
    expect(screen.getByText("SYNTHETIC")).toHaveAttribute("data-provenance", "synthetic");
  });
});

describe("console with an ad-hoc U id", () => {
  it("preselects the upload in the picker, forces live, and disables replay", async () => {
    window.history.replaceState({}, "", "/?mock=1&scenario=U001&mode=live");
    setPasscode("x");
    render(<Console catalog={catalog} />);
    const sel = screen.getByLabelText("Stopped-line scenario") as HTMLSelectElement;
    expect(sel.value).toBe("U001");
    expect(within(sel).getByRole("option", { name: /U001 · your upload/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Run live" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Replay" })).toBeDisabled();
    expect(screen.getByTestId("no-replay-note")).toBeInTheDocument();
  });
  it("asks for the passcode when none is in memory", async () => {
    window.history.replaceState({}, "", "/?mock=1&scenario=U001&mode=live");
    render(<Console catalog={catalog} />);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});

describe("upload page", () => {
  it("shows the not-enabled state without the flag", () => {
    vi.stubEnv("VITE_ENABLE_STRETCH", "");
    render(<UploadPage catalog={{ ...catalog, config: { ...MOCK_CONFIG } }} navigate={() => undefined} />);
    expect(screen.getByTestId("upload-disabled")).toHaveTextContent("Not enabled on this deployment");
  });
  it("walks upload -> mapping -> validation (mock)", async () => {
    window.history.replaceState({}, "", "/upload?mock=1");
    setPasscode("x");
    const nav = vi.fn();
    render(<UploadPage catalog={catalog} navigate={nav} />);
    const file = new File(["Timestamp,a\n1,2"], "upload_air_leak.csv", { type: "text/csv" });
    await userEvent.upload(document.querySelector('input[type="file"]')!, file);
    expect(await screen.findByText("Column mapping", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByTestId("map-Gun_Air_ST30")).toHaveTextContent(/Low confidence/);
    // make a duplicate and try to confirm
    await userEvent.selectOptions(document.getElementById(screen.getByTestId("map-Gun_Air_ST30").querySelector("select")!.id)!, "ST20-WLD");
    await userEvent.click(screen.getByRole("button", { name: /Confirm mapping/ }));
    expect(screen.getByTestId("validation-summary")).toBeInTheDocument();
    expect(nav).not.toHaveBeenCalled();
  });
  it("confirms and navigates to the live console", async () => {
    window.history.replaceState({}, "", "/upload?mock=1");
    setPasscode("x");
    const nav = vi.fn();
    render(<UploadPage catalog={catalog} navigate={nav} />);
    await userEvent.upload(document.querySelector('input[type="file"]')!, new File(["a"], "f.csv", { type: "text/csv" }));
    await userEvent.click(await screen.findByRole("button", { name: /Confirm mapping/ }, { timeout: 3000 }));
    await vi.waitFor(() => expect(nav).toHaveBeenCalledWith("/?scenario=U001&mode=live"), { timeout: 3000 });
  });
});
