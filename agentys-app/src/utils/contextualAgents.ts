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

import type { AgentState } from "../types/agent";

export type EmailContext =
  | "technical"
  | "legal"
  | "commercial"
  | "financial"
  | "medical"
  | "hr"
  | "support"
  | "onboarding"
  | "meeting"
  | "feedback";

interface SpecializedAgentConfig {
  name: string;
  displayName: string;
  context: EmailContext;
}

export const CORE_AGENTS: AgentState[] = [
  {
    name: "Classifier",
    displayName: "Email type analysis",
    status: "pending",
  },
  {
    name: "Drafter",
    displayName: "Reply drafting",
    status: "pending",
  },
  {
    name: "Critic",
    displayName: "Quality check",
    status: "pending",
  },
];

export const SPECIALIZED_AGENTS: SpecializedAgentConfig[] = [
  { name: "Technical", displayName: "Technical analysis", context: "technical" },
  { name: "Legal", displayName: "Legal review", context: "legal" },
  { name: "Commercial", displayName: "Commercial tone", context: "commercial" },
  {
    name: "Financial",
    displayName: "Financial advisor",
    context: "financial",
  },
  { name: "Medical", displayName: "Medical information", context: "medical" },
  { name: "HR", displayName: "HR specialist", context: "hr" },
  { name: "Support", displayName: "Technical support", context: "support" },
  {
    name: "Onboarding",
    displayName: "Onboarding specialist",
    context: "onboarding",
  },
  {
    name: "Meeting",
    displayName: "Meeting scheduler",
    context: "meeting",
  },
  { name: "Feedback", displayName: "Feedback analyst", context: "feedback" },
];

export function getContextualAgents(contexts: EmailContext[]): AgentState[] {
  const coreAgents = CORE_AGENTS.map((agent) => ({ ...agent }));
  const uniqueContexts = [...new Set(contexts)];

  const specializedAgents = SPECIALIZED_AGENTS.filter((agent) =>
    uniqueContexts.includes(agent.context)
  ).map(
    (agent): AgentState => ({
      name: agent.name,
      displayName: agent.displayName,
      status: "pending",
    })
  );

  return [...coreAgents, ...specializedAgents];
}
