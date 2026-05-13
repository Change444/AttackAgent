import { apiGet } from './client';
import type { ObservationReport } from './types';

export function fetchProjectObservation(projectId: string): Promise<ObservationReport> {
  return apiGet<ObservationReport>(`/projects/${projectId}/observe`);
}

export function fetchObserverReports(projectId: string): Promise<Array<{ event_id: string; payload: Record<string, unknown>; timestamp: string }>> {
  return apiGet<Array<{ event_id: string; payload: Record<string, unknown>; timestamp: string }>>(`/projects/${projectId}/observer-reports`);
}