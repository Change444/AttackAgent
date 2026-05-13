import { useState, useEffect } from 'react';
import { fetchProjects } from '../../api/projects';
import type { ProjectStatusReport } from '../../api/types';
import LoadingSpinner from '../../components/shared/LoadingSpinner';
import EmptyState from '../../components/shared/EmptyState';
import ProjectCard from './ProjectCard';
import GlobalStats from './GlobalStats';

export default function DashboardView() {
  const [projects, setProjects] = useState<ProjectStatusReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchProjects()
      .then(setProjects)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <LoadingSpinner />;
  if (error) return <EmptyState message={`Error: ${error}`} />;

  return (
    <div className="space-y-6">
      <GlobalStats projects={projects} />

      <div className="border-b border-base-600/30 pb-2">
        <h2 className="text-sm font-semibold text-base-50">Projects</h2>
      </div>

      {projects.length === 0 ? (
        <EmptyState message="No projects found. Start one via the API." />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
          {projects.map((p) => (
            <ProjectCard key={p.project_id} project={p} />
          ))}
        </div>
      )}
    </div>
  );
}