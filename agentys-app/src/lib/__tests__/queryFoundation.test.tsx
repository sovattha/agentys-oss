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

import { describe, it, expect, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import {
  getQueryClient,
  __resetQueryClientForTests,
} from "../queryClient";
import { qk } from "../queryKeys";
import {
  getWebSocketInvalidator,
  __resetWebSocketInvalidatorForTests,
} from "../webSocketInvalidator";

describe("Phase 0 — query foundation", () => {
  beforeEach(() => {
    __resetQueryClientForTests();
    __resetWebSocketInvalidatorForTests();
  });

  it("getQueryClient returns a singleton across calls", () => {
    const a = getQueryClient();
    const b = getQueryClient();
    expect(a).toBe(b);
  });

  it("query key factories produce account-canonical keys at position 1", () => {
    const intKey = qk.settings(1);
    const hexKey = qk.settings("a3f9c1d2deadbeef");
    const anonKey = qk.settings(null);

    expect(intKey).toEqual(["settings", "i:1"]);
    expect(hexKey).toEqual(["settings", "h:a3f9c1d2deadbeef"]);
    expect(anonKey).toEqual(["settings", "anon"]);

    // dual-format anchor: int 1 and string "1" must share a key
    expect(qk.settings("1")).toEqual(qk.settings(1));
  });

  it("WebSocketInvalidator attaches and detaches cleanly", () => {
    const invalidator = getWebSocketInvalidator();
    expect(invalidator.isAttached()).toBe(false);
    invalidator.attach(getQueryClient());
    expect(invalidator.isAttached()).toBe(true);
    invalidator.detach();
    expect(invalidator.isAttached()).toBe(false);
  });

  it("QueryClientProvider renders and a child useQuery resolves", async () => {
    const client = getQueryClient();
    let resolvedData: string | undefined;

    function Probe() {
      const q = useQuery({
        queryKey: ["__probe__"],
        queryFn: async () => "ok",
      });
      if (q.data) resolvedData = q.data;
      return <div data-testid="probe">{q.data ?? "loading"}</div>;
    }

    const { findByTestId } = render(
      <QueryClientProvider client={client}>
        <Probe />
      </QueryClientProvider>,
    );

    const el = await findByTestId("probe");
    // wait for the query to settle by re-reading until non-loading
    await new Promise((r) => setTimeout(r, 50));
    expect(el).toBeTruthy();
    expect(resolvedData).toBe("ok");
  });
});
