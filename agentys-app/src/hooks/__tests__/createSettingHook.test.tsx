/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

/**
 * Phase 1 regression tests for `createSettingHook`.
 *
 * The two big invariants we need to defend:
 *  1. **Boot dedup** — mounting N independent setting hooks for the same
 *     accountId triggers ONE `GET /api/settings`, not N. This is the
 *     primary win advertised by issue #690.
 *  2. **Optimistic toggle + rollback** — `toggle()` flips the visible
 *     value immediately, and a failed PATCH restores the pre-toggle value.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { act } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createSettingHook } from "../createSettingHook";

// Mock the raw HTTP layer; the hook talks to it via the queryClient.
vi.mock("../../api/settings", () => ({
  fetchAllSettings: vi.fn(),
  patchSettingsHttp: vi.fn(),
}));

import { fetchAllSettings, patchSettingsHttp } from "../../api/settings";

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 30_000, gcTime: 30 * 60_000 },
      mutations: { retry: false },
    },
  });
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, Wrapper };
}

describe("createSettingHook — Phase 1", () => {
  beforeEach(() => {
    vi.mocked(fetchAllSettings).mockReset();
    vi.mocked(patchSettingsHttp).mockReset();
  });

  it("collapses N hooks for the same account into ONE GET /api/settings", async () => {
    vi.mocked(fetchAllSettings).mockResolvedValue({
      auto_reply_enabled: true,
      deep_work_enabled: false,
      auto_followup_enabled: true,
    });

    const useAutoReply = createSettingHook({
      settingKey: "auto_reply_enabled",
      hookName: "useAutoReply",
    });
    const useDeepWork = createSettingHook({
      settingKey: "deep_work_enabled",
      hookName: "useDeepWork",
    });
    const useAutoFollowup = createSettingHook({
      settingKey: "auto_followup_enabled",
      hookName: "useAutoFollowup",
    });

    function Probe() {
      const a = useAutoReply(1);
      const b = useDeepWork(1);
      const c = useAutoFollowup(1);
      return (
        <>
          <span data-testid="a">{String(a.value)}</span>
          <span data-testid="b">{String(b.value)}</span>
          <span data-testid="c">{String(c.value)}</span>
        </>
      );
    }

    const { Wrapper } = makeWrapper();
    render(
      <Wrapper>
        <Probe />
      </Wrapper>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("a").textContent).toBe("true");
      expect(screen.getByTestId("b").textContent).toBe("false");
      expect(screen.getByTestId("c").textContent).toBe("true");
    });

    // The hard invariant: ONE network call for three subscribers.
    expect(vi.mocked(fetchAllSettings)).toHaveBeenCalledTimes(1);
  });

  it("does NOT share cache across distinct accounts", async () => {
    vi.mocked(fetchAllSettings).mockResolvedValue({
      deep_work_enabled: true,
    });

    const useDeepWork = createSettingHook({
      settingKey: "deep_work_enabled",
      hookName: "useDeepWork",
    });

    function Probe() {
      const a = useDeepWork(1);
      const b = useDeepWork(2);
      return (
        <>
          <span data-testid="a">{String(a.value)}</span>
          <span data-testid="b">{String(b.value)}</span>
        </>
      );
    }

    const { Wrapper } = makeWrapper();
    render(
      <Wrapper>
        <Probe />
      </Wrapper>,
    );

    // Two different account scopes → two fetches (each cache key is distinct).
    await waitFor(() => {
      expect(vi.mocked(fetchAllSettings)).toHaveBeenCalledTimes(2);
    });
  });

  it("optimistic toggle flips immediately and persists on PATCH success", async () => {
    vi.mocked(fetchAllSettings).mockResolvedValue({
      deep_work_enabled: false,
    });
    let resolvePatch: () => void = () => {};
    vi.mocked(patchSettingsHttp).mockImplementation(
      () => new Promise<void>((resolve) => { resolvePatch = resolve; }),
    );

    const useDeepWork = createSettingHook({
      settingKey: "deep_work_enabled",
      hookName: "useDeepWork",
    });

    let captured: { value: boolean; toggle: () => Promise<boolean> } | null = null;
    function Probe() {
      const s = useDeepWork(1);
      captured = s;
      return <span data-testid="v">{String(s.value)}</span>;
    }

    const { Wrapper } = makeWrapper();
    render(
      <Wrapper>
        <Probe />
      </Wrapper>,
    );

    await waitFor(() => expect(screen.getByTestId("v").textContent).toBe("false"));

    // Fire the toggle but don't await — we want to observe the OPTIMISTIC
    // state before the PATCH resolves. Use waitFor (poll-until-true) so the
    // assertion tolerates any number of microtasks needed for React + the
    // mutation cache to settle the optimistic setQueryData. The PATCH
    // promise stays unresolved, so observing "true" before resolving the
    // PATCH still proves the OPTIMISTIC path drove the flip.
    let togglePromise: Promise<boolean>;
    act(() => {
      togglePromise = captured!.toggle();
    });

    await waitFor(() => {
      expect(screen.getByTestId("v").textContent).toBe("true");
    });

    await act(async () => {
      resolvePatch();
      await togglePromise!;
    });

    expect(screen.getByTestId("v").textContent).toBe("true");
    expect(vi.mocked(patchSettingsHttp)).toHaveBeenCalledWith({
      deep_work_enabled: true,
    });
  });

  it("rolls back optimistic value when PATCH fails", async () => {
    vi.mocked(fetchAllSettings).mockResolvedValue({
      deep_work_enabled: false,
    });
    vi.mocked(patchSettingsHttp).mockRejectedValueOnce(new Error("500"));

    const useDeepWork = createSettingHook({
      settingKey: "deep_work_enabled",
      hookName: "useDeepWork",
    });

    let captured: { value: boolean; toggle: () => Promise<boolean> } | null = null;
    function Probe() {
      const s = useDeepWork(1);
      captured = s;
      return <span data-testid="v">{String(s.value)}</span>;
    }

    const { Wrapper } = makeWrapper();
    render(
      <Wrapper>
        <Probe />
      </Wrapper>,
    );

    await waitFor(() => expect(screen.getByTestId("v").textContent).toBe("false"));

    // Swallow the expected console.error so test output stays clean.
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    let result: boolean = true;
    await act(async () => {
      result = await captured!.toggle();
    });

    expect(result).toBe(false);
    // Post-rollback the value is back to the original.
    expect(screen.getByTestId("v").textContent).toBe("false");
    errSpy.mockRestore();
  });
});
