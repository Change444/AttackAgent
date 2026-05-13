import { apiGet } from './client';
import type { MemoryEntry } from './types';

export function fetchProjectMemory(projectId: string): Promise<MemoryEntry[]> {
  return apiGet<MemoryEntry[]>(`/projects/${projectId}/memory`);
}