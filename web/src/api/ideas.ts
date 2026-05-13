import { apiGet } from './client';
import type { IdeaEntry } from './types';

export function fetchProjectIdeas(projectId: string): Promise<IdeaEntry[]> {
  return apiGet<IdeaEntry[]>(`/projects/${projectId}/ideas`);
}