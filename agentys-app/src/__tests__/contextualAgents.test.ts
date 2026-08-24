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
import {
  getContextualAgents,
  CORE_AGENTS,
  SPECIALIZED_AGENTS,
  type EmailContext,
} from "../utils/contextualAgents";

describe("getContextualAgents", () => {
  it("retourne uniquement les agents core quand aucun contexte", () => {
    const agents = getContextualAgents([]);

    expect(agents).toHaveLength(3);
    expect(agents.map((a) => a.name)).toEqual([
      "Classifier",
      "Drafter",
      "Critic",
    ]);
  });

  it("retourne les agents core pour tous les contextes", () => {
    const contexts: EmailContext[] = ["technical", "legal", "commercial"];
    const agents = getContextualAgents(contexts);

    const coreAgentNames = CORE_AGENTS.map((a) => a.name);
    for (const coreName of coreAgentNames) {
      expect(agents.find((a) => a.name === coreName)).toBeDefined();
    }
  });

  it("ajoute l'agent Technical pour le contexte 'technical'", () => {
    const agents = getContextualAgents(["technical"]);

    expect(agents.find((a) => a.name === "Technical")).toBeDefined();
    expect(agents.find((a) => a.name === "Technical")?.displayName).toBe(
      "Technical analysis"
    );
  });

  it("ajoute l'agent Legal pour le contexte 'legal'", () => {
    const agents = getContextualAgents(["legal"]);

    expect(agents.find((a) => a.name === "Legal")).toBeDefined();
    expect(agents.find((a) => a.name === "Legal")?.displayName).toBe(
      "Legal review"
    );
  });

  it("ajoute l'agent Commercial pour le contexte 'commercial'", () => {
    const agents = getContextualAgents(["commercial"]);

    expect(agents.find((a) => a.name === "Commercial")).toBeDefined();
    expect(agents.find((a) => a.name === "Commercial")?.displayName).toBe(
      "Commercial tone"
    );
  });

  it("gere plusieurs contextes simultanement", () => {
    const agents = getContextualAgents(["technical", "legal"]);

    expect(agents.find((a) => a.name === "Technical")).toBeDefined();
    expect(agents.find((a) => a.name === "Legal")).toBeDefined();
    expect(agents).toHaveLength(5); // 3 core + 2 specialized
  });

  it("ne duplique pas les agents pour des contextes redondants", () => {
    const agents = getContextualAgents(["technical", "technical"]);

    const technicalAgents = agents.filter((a) => a.name === "Technical");
    expect(technicalAgents).toHaveLength(1);
  });

  it("retourne tous les agents specialises pour tous les contextes", () => {
    const allContexts: EmailContext[] = [
      "technical",
      "legal",
      "commercial",
      "financial",
      "medical",
      "hr",
      "support",
      "onboarding",
      "meeting",
      "feedback",
    ];
    const agents = getContextualAgents(allContexts);

    const expectedCount = CORE_AGENTS.length + SPECIALIZED_AGENTS.length;
    expect(agents).toHaveLength(expectedCount);
  });

  it("place les agents core avant les agents specialises", () => {
    const agents = getContextualAgents(["commercial", "legal"]);

    const coreCount = CORE_AGENTS.length;
    const firstAgents = agents.slice(0, coreCount);
    const coreNames = CORE_AGENTS.map((a) => a.name);

    for (const agent of firstAgents) {
      expect(coreNames).toContain(agent.name);
    }
  });

  it("initialise les agents specialises avec le statut 'pending'", () => {
    const agents = getContextualAgents(["technical"]);

    const technicalAgent = agents.find((a) => a.name === "Technical");
    expect(technicalAgent?.status).toBe("pending");
  });
});

describe("CORE_AGENTS", () => {
  it("contient Classifier, Drafter et Critic", () => {
    const names = CORE_AGENTS.map((a) => a.name);
    expect(names).toContain("Classifier");
    expect(names).toContain("Drafter");
    expect(names).toContain("Critic");
  });

  it("has displayNames for each agent", () => {
    expect(CORE_AGENTS.find((a) => a.name === "Classifier")?.displayName).toBe(
      "Email type analysis"
    );
    expect(CORE_AGENTS.find((a) => a.name === "Drafter")?.displayName).toBe(
      "Reply drafting"
    );
    expect(CORE_AGENTS.find((a) => a.name === "Critic")?.displayName).toBe(
      "Quality check"
    );
  });
});

describe("SPECIALIZED_AGENTS", () => {
  it("contient tous les agents specialises du TODO", () => {
    const names = SPECIALIZED_AGENTS.map((a) => a.name);
    expect(names).toContain("Technical");
    expect(names).toContain("Legal");
    expect(names).toContain("Commercial");
  });

  it("chaque agent a un contexte associe", () => {
    for (const agent of SPECIALIZED_AGENTS) {
      expect(agent.context).toBeDefined();
    }
  });
});
