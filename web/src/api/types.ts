// TypeScript interfaces mirroring L9 API response shapes

export interface ProjectStatusReport {
  project_id: string;
  challenge_id: string;
  status: string;
  solver_count: number;
  idea_count: number;
  fact_count: number;
  pending_review_count: number;
  candidate_flags: string[];
  last_observation_severity: string;
}

export interface IdeaEntry {
  idea_id: string;
  project_id: string;
  description: string;
  status: IdeaStatus;
  solver_id: string;
  priority: number;
  failure_boundary_refs: string[];
}

export type IdeaStatus = 'pending' | 'claimed' | 'testing' | 'verified' | 'failed' | 'shelved';

export interface MemoryEntry {
  entry_id: string;
  project_id: string;
  kind: MemoryKind;
  content: string;
  evidence_refs: string[];
  confidence: number;
  created_at: string;
}

export type MemoryKind = 'fact' | 'credential' | 'endpoint' | 'failure_boundary' | 'hint' | 'session_state';

export interface SolverSession {
  solver_id: string;
  project_id: string;
  profile: string;
  status: SolverStatus;
  active_idea_id: string;
  local_memory_ids: string[];
  budget_remaining: number;
  scratchpad_summary: string;
  recent_event_ids: string[];
}

export type SolverStatus = 'created' | 'assigned' | 'running' | 'waiting_review' | 'completed' | 'failed' | 'expired' | 'cancelled';

export interface ReviewRequest {
  request_id: string;
  project_id: string;
  requested_by: string;
  action_type: string;
  risk_level: string;
  title: string;
  description: string;
  evidence_refs: string[];
  proposed_action: string;
  proposed_action_payload: Record<string, unknown>;
  alternatives: string[];
  timeout_policy: string;
  status: ReviewStatus;
  decision: string;
  decided_by: string;
  decided_at: string;
}

export type ReviewStatus = 'pending' | 'approved' | 'rejected' | 'modified' | 'expired';

export interface KnowledgePacket {
  packet_id: string;
  project_id: string;
  packet_type: KnowledgePacketType;
  source_solver_id: string;
  content: string;
  confidence: number;
  evidence_refs: string[];
  routing_priority: number;
  suggested_recipients: string[];
  merge_status: string;
  merged_from_ids: string[];
  created_at: string;
}

export type KnowledgePacketType = 'fact' | 'idea' | 'failure_boundary' | 'credential' | 'endpoint' | 'artifact_summary' | 'candidate_flag' | 'help_request';

export interface ObservationReport {
  report_id: string;
  project_id: string;
  observations: ObservationNote[];
  severity: string;
  suggested_actions: string[];
  intervention_level: InterventionLevel;
  recommended_action: string | null;
}

export type InterventionLevel = 'observe' | 'reminder' | 'steer' | 'throttle' | 'stop_reassign' | 'safety_block';

export interface ObservationNote {
  kind: string;
  description: string;
  solver_id: string;
  evidence_refs: string[];
}

export interface BlackboardEvent {
  event_id: string;
  project_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  source: string;
  timestamp: string;
  causal_ref: string | null;
}

export interface MaterializedState {
  project: TeamProject | null;
  facts: MemoryEntry[];
  ideas: IdeaEntry[];
  sessions: SolverSession[];
  packets: KnowledgePacket[];
}

export interface TeamProject {
  project_id: string;
  challenge_id: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ReplayStep {
  step_index: number;
  event_type: string;
  timestamp: string;
  payload: Record<string, unknown>;
  explanation: string;
  state_summary: {
    status: string | null;
    fact_count: number;
    idea_count: number;
    solver_count: number;
  };
}

export interface RunMetrics {
  solve_success: boolean;
  total_cycles: number;
  failed_attempts: number;
  review_count: number;
  policy_blocks: number;
  submission_attempts: number;
  repeated_failure_rate: number;
  stagnation_events: number;
  observation_severity_counts: Record<string, number>;
  budget_consumed: number;
  idea_claim_rate: number;
}

export interface SSEEvent {
  event_id: string;
  project_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

export type SSEChannel = 'project_updated' | 'solver_updated' | 'idea_updated' | 'memory_added' | 'observer_reported' | 'review_created' | 'review_decided' | 'candidate_flag_found' | 'tool_event' | 'hint_added' | 'knowledge_published' | 'knowledge_merged';

export interface PrimitiveActionSpec {
  name: string;
  capability: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  cost: number;
  risk: string;
}