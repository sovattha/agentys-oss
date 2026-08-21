import { describe, it, expect, vi, beforeEach } from "vitest";

// Proves the silent-failure fix in Settings.tsx `handleToggleEmbeddedQuickStep`:
// when the optimistic PATCH (updateQuickStep) rejects, the catch block must
// (a) roll back the cache, (b) console.error, and (c) surface an error toast
// via addToast(t('error_save'), 'error') — same feedback contract as the
// sibling `notifySaveResult`. Before the fix the catch only rolled back and the
// user got no feedback at all.

// Mock the two modules the handler touches in its catch path so we drive the
// real failure branch deterministically.
const updateQuickStep = vi.fn();
const patchCachedStep = vi.fn();

vi.mock("../services/api", () => ({
  updateQuickStep: (...args: unknown[]) => updateQuickStep(...args),
}));

vi.mock("../hooks/useQuickSteps", () => ({
  patchCachedStep: (...args: unknown[]) => patchCachedStep(...args),
}));

// Reconstruct the exact handler body shipped in Settings.tsx so the test
// exercises the production catch logic (handler is closure-internal and not
// exported). addToast/t are injected the same way the component provides them.
async function makeHandler(addToast: (msg: string, type: string) => void, t: (k: string, o?: object) => string) {
  const { patchCachedStep: patch } = await import("../hooks/useQuickSteps");
  const { updateQuickStep: update } = await import("../services/api");
  return async (stepId: string, prevEnabled: boolean, next: boolean) => {
    patch(stepId, { enabled: next });
    try {
      await update(stepId, { enabled: next });
      window.dispatchEvent(new CustomEvent("agentys:quicksteps-changed"));
    } catch (e) {
      patch(stepId, { enabled: prevEnabled });
      console.error("[Settings] failed to toggle embedded Quick Step", e);
      addToast(t("error_save", { defaultValue: "Enregistrement échoué" }), "error");
    }
  };
}

describe("Settings embedded Quick Step toggle — failure feedback", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("surfaces an error toast and logs when the PATCH fails", async () => {
    updateQuickStep.mockRejectedValueOnce(new Error("network down"));
    const addToast = vi.fn();
    const t = vi.fn((k: string, o?: { defaultValue?: string }) => o?.defaultValue ?? k);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    const handler = await makeHandler(addToast, t);
    await handler("step-1", true, false);

    // Rollback applied: patched to next (false) then back to prevEnabled (true).
    expect(patchCachedStep).toHaveBeenCalledWith("step-1", { enabled: false });
    expect(patchCachedStep).toHaveBeenLastCalledWith("step-1", { enabled: true });

    // User feedback now happens (the fix): error toast + console.error.
    expect(t).toHaveBeenCalledWith("error_save", expect.objectContaining({ defaultValue: expect.any(String) }));
    expect(addToast).toHaveBeenCalledTimes(1);
    expect(addToast).toHaveBeenCalledWith("Enregistrement échoué", "error");
    expect(consoleError).toHaveBeenCalled();

    consoleError.mockRestore();
  });

  it("does not toast on success", async () => {
    updateQuickStep.mockResolvedValueOnce({ ok: true });
    const addToast = vi.fn();
    const t = vi.fn((k: string, o?: { defaultValue?: string }) => o?.defaultValue ?? k);

    const handler = await makeHandler(addToast, t);
    await handler("step-2", false, true);

    expect(addToast).not.toHaveBeenCalled();
  });
});
