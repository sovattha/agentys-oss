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
 * Phase 2 regression tests for `useLabels`.
 *
 * Invariants the migration must defend:
 *  1. **Single fetch per account at boot** — `fetchLabels` and
 *     `fetchLabelCounts` each fire exactly once when multiple consumers
 *     mount under the same account. (Eliminates the manual debounce that
 *     used to live at `useLabels.ts:42-77`.)
 *  2. **Optimistic toggle survives an in-flight PATCH** — flipping a
 *     favorite reflects in the cached list before the API resolves.
 *  3. **Account switch re-fires the queries** — flipping the active
 *     account id triggers fresh fetches under the new query key.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { act } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("../../api/labels", () => ({
  fetchLabels: vi.fn(),
  fetchLabelCounts: vi.fn(),
  toggleLabelFavorite: vi.fn(),
  saveFavoriteLabelOrder: vi.fn(),
  getFavoriteLabelOrder: vi.fn(() => []),
}));

// Active account is read via getActiveAccountId — control it directly.
let _activeId = "1";
vi.mock("../../api/emails", () => ({
  getActiveAccountId: () => _activeId,
}));

import {
  fetchLabels,
  fetchLabelCounts,
  toggleLabelFavorite,
} from "../../api/labels";
import { useLabels } from "../useLabels";
import type { Label } from "../../types/labels";

function makeLabel(name: string, is_favorite = false): Label {
  return {
    name,
    color: "#888",
    description: "",
    is_default: false,
    is_favorite,
    created_at: "",
    rules: [],
  };
}

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

describe("useLabels — Phase 2", () => {
  beforeEach(() => {
    _activeId = "1";
    vi.mocked(fetchLabels).mockReset();
    vi.mocked(fetchLabelCounts).mockReset();
    vi.mocked(toggleLabelFavorite).mockReset();
  });

  it("collapses N consumers into ONE fetchLabels + ONE fetchLabelCounts", async () => {
    vi.mocked(fetchLabels).mockResolvedValue({
      labels: [makeLabel("Action", true), makeLabel("Project X")],
      count: 2,
    });
    vi.mocked(fetchLabelCounts).mockResolvedValue({
      counts: { Action: 3, "Project X": 1 },
      total: 4,
    });

    function Probe() {
      const a = useLabels();
      const b = useLabels();
      const c = useLabels();
      return (
        <>
          <span data-testid="a">{String(a.labels.length)}</span>
          <span data-testid="b">{String(b.labels.length)}</span>
          <span data-testid="c">{String(c.labels.length)}</span>
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
      expect(screen.getByTestId("a").textContent).toBe("2");
    });

    // Hard invariant: in-flight dedup + staleTime collapse to single calls.
    expect(vi.mocked(fetchLabels)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetchLabelCounts)).toHaveBeenCalledTimes(1);
  });

  it("optimistic toggleFavorite swaps the label in cache before refetch", async () => {
    vi.mocked(fetchLabels).mockResolvedValue({
      labels: [makeLabel("Action", false)],
      count: 1,
    });
    vi.mocked(fetchLabelCounts).mockResolvedValue({
      counts: { Action: 1 },
      total: 1,
    });
    vi.mocked(toggleLabelFavorite).mockResolvedValue({
      label: makeLabel("Action", true),
      message: "ok",
    });

    let captured: ReturnType<typeof useLabels> | null = null;
    function Probe() {
      const s = useLabels();
      captured = s;
      const action = s.labels.find((l) => l.name === "Action");
      return <span data-testid="fav">{String(action?.is_favorite ?? "?")}</span>;
    }

    const { Wrapper } = makeWrapper();
    render(
      <Wrapper>
        <Probe />
      </Wrapper>,
    );

    await waitFor(() => expect(screen.getByTestId("fav").textContent).toBe("false"));

    await act(async () => {
      await captured!.toggleFavorite("Action");
    });

    expect(screen.getByTestId("fav").textContent).toBe("true");
    expect(vi.mocked(toggleLabelFavorite)).toHaveBeenCalledWith("Action", true);
  });

  it("skips fetches before an account is bound (no 401 spam)", async () => {
    _activeId = "default";
    vi.mocked(fetchLabels).mockResolvedValue({ labels: [], count: 0 });
    vi.mocked(fetchLabelCounts).mockResolvedValue({ counts: {}, total: 0 });

    function Probe() {
      const s = useLabels();
      return <span data-testid="n">{String(s.labels.length)}</span>;
    }

    const { Wrapper } = makeWrapper();
    render(
      <Wrapper>
        <Probe />
      </Wrapper>,
    );

    // Give the queries time to (not) fire.
    await new Promise((r) => setTimeout(r, 50));

    expect(vi.mocked(fetchLabels)).not.toHaveBeenCalled();
    expect(vi.mocked(fetchLabelCounts)).not.toHaveBeenCalled();
    expect(screen.getByTestId("n").textContent).toBe("0");
  });

  it("account switch flips the query key and triggers a fresh fetch", async () => {
    vi.mocked(fetchLabels).mockImplementation(async () => {
      const labels = _activeId === "1"
        ? [makeLabel("A1")]
        : [makeLabel("A2"), makeLabel("B2")];
      return { labels, count: labels.length };
    });
    vi.mocked(fetchLabelCounts).mockResolvedValue({ counts: {}, total: 0 });

    function Probe() {
      const s = useLabels();
      return <span data-testid="n">{String(s.labels.length)}</span>;
    }

    const { Wrapper } = makeWrapper();
    render(
      <Wrapper>
        <Probe />
      </Wrapper>,
    );

    await waitFor(() => expect(screen.getByTestId("n").textContent).toBe("1"));
    expect(vi.mocked(fetchLabels)).toHaveBeenCalledTimes(1);

    // Switch account: mutate the source and dispatch the event the hook listens to.
    await act(async () => {
      _activeId = "2";
      window.dispatchEvent(new Event("agentys:account-changed"));
    });

    await waitFor(() => expect(screen.getByTestId("n").textContent).toBe("2"));
    expect(vi.mocked(fetchLabels)).toHaveBeenCalledTimes(2);
  });
});
