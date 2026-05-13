import { apiGet } from './client';
import type { ReplayStep, RunMetrics } from './types';

export function fetchReplayTimeline(projectId: string): Promise<ReplayStep[]> {
  return apiGet<ReplayStep[]>(`/projects/${projectId}/replay-timeline`);
}

export function fetchMetrics(projectId: string): Promise<RunMetrics> {
  return apiGet<RunMetrics>(`/projects/${projectId}/metrics`);
}