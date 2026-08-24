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

export type AgentStatusType = "pending" | "in_progress" | "completed" | "rejected";

export interface AgentDetailedInfo {
  prompt?: string;
  tokensUsed?: number;
  processingTimeMs?: number;
  // Classifier details
  classification?: string;
  priority?: number;
  // Drafter details
  output?: string;
  // Critic details
  isValid?: boolean;
  feedback?: string;
}

export interface AgentState {
  name: string;
  displayName: string;
  status: AgentStatusType;
  message?: string;
  details?: AgentDetailedInfo;
}

export type DecisionType = "classified" | "drafted" | "approved" | "rejected" | "revised";

export interface AgentDecision {
  id: string;
  agent: string;
  type: DecisionType;
  message: string;
  timestamp: Date;
  version?: number;
}
