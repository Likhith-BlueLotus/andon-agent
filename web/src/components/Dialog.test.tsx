import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { Dialog } from "./Dialog";

function Harness({ onClose }: { onClose: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>opener</button>
      {open && (
        <Dialog title="Evidence" labelId="t" onClose={() => { setOpen(false); onClose(); }}>
          <button>first</button>
          <button>last</button>
        </Dialog>
      )}
    </>
  );
}

describe("Dialog", () => {
  it("is a labelled modal dialog that traps focus, closes on Esc and restores focus", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    const opener = screen.getByText("opener");
    await user.click(opener);
    const dlg = screen.getByRole("dialog", { name: "Evidence" });
    expect(dlg).toHaveAttribute("aria-modal", "true");
    expect(dlg.contains(document.activeElement)).toBe(true);
    for (let i = 0; i < 6; i++) {
      await user.tab();
      expect(dlg.contains(document.activeElement)).toBe(true);
    }
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });
});
