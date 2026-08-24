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
import { isThemeId } from "./useTheme";

/**
 * "Clarity" (default) est désormais le seul thème. Dark Luxury et Futurist ont
 * été retirés. isThemeId est la porte de coercion : tout thème legacy persisté
 * (localStorage OU backend) doit être rejeté ici pour retomber sur "default".
 */
describe("isThemeId — coercion des thèmes retirés vers default", () => {
  it('accepte "default"', () => {
    expect(isThemeId("default")).toBe(true);
  });

  it('rejette les thèmes supprimés "dark-luxury" et "futurist"', () => {
    expect(isThemeId("dark-luxury")).toBe(false);
    expect(isThemeId("futurist")).toBe(false);
  });

  it("rejette toute valeur inconnue ou null", () => {
    expect(isThemeId("futurist-silver")).toBe(false);
    expect(isThemeId("dark")).toBe(false);
    expect(isThemeId("")).toBe(false);
    expect(isThemeId(null)).toBe(false);
  });
});
