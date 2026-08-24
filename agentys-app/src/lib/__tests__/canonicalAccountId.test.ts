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

import { describe, it, expect } from "vitest";
import { canonicalAccountId } from "../canonicalAccountId";

describe("canonicalAccountId", () => {
  describe("anon bucket", () => {
    it.each([
      ["null", null],
      ["undefined", undefined],
      ["empty string", ""],
      ["whitespace string", "   "],
      ["literal 'default'", "default"],
      ["string '0'", "0"],
      ["number 0", 0],
      ["NaN", Number.NaN],
      ["Infinity", Number.POSITIVE_INFINITY],
    ])("maps %s → 'anon'", (_label, input) => {
      expect(canonicalAccountId(input as never)).toBe("anon");
    });
  });

  describe("integer form (/api/init)", () => {
    it("maps number 1 → 'i:1'", () => {
      expect(canonicalAccountId(1)).toBe("i:1");
    });
    it("maps number 42 → 'i:42'", () => {
      expect(canonicalAccountId(42)).toBe("i:42");
    });
    it("truncates decimals (defensive)", () => {
      expect(canonicalAccountId(3.7)).toBe("i:3");
    });
    it("collapses '1' and 1 to the same key", () => {
      expect(canonicalAccountId("1")).toBe(canonicalAccountId(1));
    });
  });

  describe("hex form (/api/accounts)", () => {
    it("maps a hex hash → 'h:<lowered>'", () => {
      expect(canonicalAccountId("a3F9c1d2DEADBEEF")).toBe("h:a3f9c1d2deadbeef");
    });
    it("requires at least one a-f to be treated as hex", () => {
      // pure decimal-looking string goes through integer path, not hex
      expect(canonicalAccountId("123456")).toBe("i:123456");
    });
    it("does not collide with the integer form (prefix discrimination)", () => {
      // hex string "1a" must never collide with integer 1
      expect(canonicalAccountId("1a")).not.toBe(canonicalAccountId(1));
    });
  });

  describe("fallback bucket", () => {
    it("non-hex, non-decimal strings fall through to 's:'", () => {
      expect(canonicalAccountId("user@example.com")).toBe("s:user@example.com");
    });
  });

  it("is a total function (never throws on any input)", () => {
    // defensive: even nonsense shapes must produce a string
    expect(() => canonicalAccountId(undefined)).not.toThrow();
    expect(() => canonicalAccountId(null)).not.toThrow();
    expect(() => canonicalAccountId({} as never)).not.toThrow();
  });
});
