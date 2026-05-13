import { apiGet } from './client';
import type { SolverSession } from './types';

export function fetchProjectSolvers(projectId: string): Promise<SolverSession[]> {
  return apiGet<SolverSession[]>(`/projects/${projectId}/solvers`);
}