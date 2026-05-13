import { apiGet, apiPost } from './client';
import type { ProjectStatusReport, MaterializedState } from './types';

export function fetchProjects(): Promise<ProjectStatusReport[]> {
  return apiGet<ProjectStatusReport[]>('/projects');
}

export function fetchProjectStatus(projectId: string): Promise<ProjectStatusReport> {
  return apiGet<ProjectStatusReport>(`/projects/${projectId}`);
}

export function startProject(challengeId: string): Promise<{ project_id: string; status: string }> {
  return apiPost<{ project_id: string; status: string }>('/projects/start-project', { challenge_id: challengeId });
}

export function pauseProject(projectId: string): Promise<{ project_id: string; status: string }> {
  return apiPost<{ project_id: string; status: string }>(`/projects/${projectId}/pause`);
}

export function resumeProject(projectId: string): Promise<{ project_id: string; status: string }> {
  return apiPost<{ project_id: string; status: string }>(`/projects/${projectId}/resume`);
}

export function addHint(projectId: string, hint: string): Promise<Record<string, string>> {
  return apiPost<Record<string, string>>(`/projects/${projectId}/hint`, { hint });
}

export function fetchGraph(projectId: string): Promise<MaterializedState> {
  return apiGet<MaterializedState>(`/projects/${projectId}/graph`);
}