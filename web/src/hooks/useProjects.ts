import { useState, useEffect, useCallback } from 'react';
import { fetchProjects } from '../api/projects';
import type { ProjectStatusReport, SSEEvent } from '../api/types';
import { useSSEContext } from '../context/SSEContext';

export function useProjects() {
  const [projects, setProjects] = useState<ProjectStatusReport[]>([]);
  const [loading, setLoading] = useState(true);
  const { subscribe, unsubscribe } = useSSEContext();

  useEffect(() => {
    fetchProjects()
      .then(setProjects)
      .finally(() => setLoading(false));
  }, []);

  const handleSSE = useCallback((event: SSEEvent) => {
    setProjects((prev) => {
      const updated = prev.map((p) =>
        p.project_id === event.project_id
          ? { ...p, ...(event.payload as unknown as Partial<ProjectStatusReport>) }
          : p
      );
      if (!prev.find((p) => p.project_id === event.project_id)) {
        return [...prev, event.payload as unknown as ProjectStatusReport];
      }
      return updated;
    });
  }, []);

  useEffect(() => {
    subscribe('project_updated', handleSSE);
    return () => unsubscribe('project_updated', handleSSE);
  }, [subscribe, unsubscribe, handleSSE]);

  return { projects, loading };
}