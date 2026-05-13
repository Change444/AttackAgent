import { apiGet } from './client';

export function fetchCandidateFlags(projectId: string): Promise<Array<{ event_id: string; payload: Record<string, unknown>; timestamp: string }>> {
  return apiGet<Array<{ event_id: string; payload: Record<string, unknown>; timestamp: string }>>(`/projects/${projectId}/candidate-flags`);
}