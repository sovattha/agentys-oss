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
