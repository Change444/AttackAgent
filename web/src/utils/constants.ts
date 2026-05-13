// Status colors grouped by domain to avoid key collisions

export const PROJECT_STATUS_COLORS: Record<string, string> = {
  new: 'bg-base-400 text-base-50',
  running: 'bg-cyan text-base-900',
  paused: 'bg-amber text-base-900',
  done: 'bg-cyan-dark text-cyan-light',
  abandoned: 'bg-danger-dark text-danger-light',
};

export const SOLVER_STATUS_COLORS: Record<string, string> = {
  created: 'bg-base-500 text-base-100',
  assigned: 'bg-amber/20 text-amber',
  running: 'bg-cyan/20 text-cyan',
  waiting_review: 'bg-amber/20 text-amber',
  completed: 'bg-cyan-dark/20 text-cyan',
  failed: 'bg-danger/20 text-danger',
  expired: 'bg-base-500/20 text-slate-dark',
  cancelled: 'bg-base-500/20 text-slate-dark',
};

export const IDEA_STATUS_COLORS: Record<string, string> = {
  pending: 'bg-base-400 text-base-50',
  claimed: 'bg-amber/20 text-amber',
  testing: 'bg-cyan/20 text-cyan-light',
  verified: 'bg-cyan text-base-900',
  failed: 'bg-danger text-base-900',
  shelved: 'bg-base-500/20 text-slate-dark',
};

export const REVIEW_STATUS_COLORS: Record<string, string> = {
  pending: 'bg-amber/20 text-amber',
  approved: 'bg-cyan/20 text-cyan',
  rejected: 'bg-danger/20 text-danger',
  modified: 'bg-cyan-light/20 text-cyan-light',
  expired: 'bg-base-500/20 text-slate-dark',
};

export const INTERVENTION_COLORS: Record<string, string> = {
  observe: 'bg-base-400 text-base-50',
  reminder: 'bg-amber/20 text-amber',
  steer: 'bg-amber text-base-900',
  throttle: 'bg-amber-dark text-amber-light',
  stop_reassign: 'bg-danger/20 text-danger',
  safety_block: 'bg-danger text-base-900',
};

export const RISK_COLORS: Record<string, string> = {
  low: 'bg-cyan/20 text-cyan',
  medium: 'bg-amber/20 text-amber',
  high: 'bg-danger/20 text-danger',
  critical: 'bg-danger text-base-900',
};

export const KIND_LABELS: Record<string, string> = {
  fact: 'Fact',
  credential: 'Credential',
  endpoint: 'Endpoint',
  failure_boundary: 'Boundary',
  hint: 'Hint',
  session_state: 'Session',
};

export const KIND_COLORS: Record<string, string> = {
  fact: 'bg-cyan/20 text-cyan',
  credential: 'bg-amber/20 text-amber',
  endpoint: 'bg-base-400/20 text-slate-light',
  failure_boundary: 'bg-danger/20 text-danger',
  hint: 'bg-amber/20 text-amber-light',
  session_state: 'bg-base-500/20 text-slate',
};

export const SEVERITY_COLORS: Record<string, string> = {
  info: 'text-cyan',
  warning: 'text-amber',
  critical: 'text-danger',
};

// Generic status badge resolver: pick the right color map by domain
export function getStatusColor(domain: 'project' | 'solver' | 'idea' | 'review' | 'intervention' | 'risk', status: string): string {
  const maps: Record<string, Record<string, string>> = {
    project: PROJECT_STATUS_COLORS,
    solver: SOLVER_STATUS_COLORS,
    idea: IDEA_STATUS_COLORS,
    review: REVIEW_STATUS_COLORS,
    intervention: INTERVENTION_COLORS,
    risk: RISK_COLORS,
  };
  return maps[domain]?.[status] || 'bg-base-500 text-slate';
}