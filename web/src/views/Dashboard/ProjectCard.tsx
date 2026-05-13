import { Link } from 'react-router-dom';
import type { ProjectStatusReport } from '../../api/types';
import StatusBadge from '../../components/shared/StatusBadge';

export default function ProjectCard({ project }: { project: ProjectStatusReport }) {
  return (
    <Link to={`/projects/${project.project_id}`} className="block">
      <div className="bg-base-800 rounded-lg border border-base-600/30 hover:border-amber/30 transition-colors p-4 cursor-pointer">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="text-sm font-semibold text-base-50 font-mono">{project.project_id}</h3>
            <p className="text-xs text-slate-dark mt-0.5">{project.challenge_id}</p>
          </div>
          <StatusBadge status={project.status} domain="project" />
        </div>

        <div className="grid grid-cols-4 gap-2 text-center">
          <div className="bg-base-700/50 rounded-md p-2">
            <p className="text-xs text-slate-dark">Solvers</p>
            <p className="text-sm font-mono font-semibold text-base-50">{project.solver_count}</p>
          </div>
          <div className="bg-base-700/50 rounded-md p-2">
            <p className="text-xs text-slate-dark">Ideas</p>
            <p className="text-sm font-mono font-semibold text-base-50">{project.idea_count}</p>
          </div>
          <div className="bg-base-700/50 rounded-md p-2">
            <p className="text-xs text-slate-dark">Facts</p>
            <p className="text-sm font-mono font-semibold text-base-50">{project.fact_count}</p>
          </div>
          <div className="bg-base-700/50 rounded-md p-2">
            <p className="text-xs text-slate-dark">Reviews</p>
            <p className="text-sm font-mono font-semibold text-amber">{project.pending_review_count}</p>
          </div>
        </div>

        {project.candidate_flags.length > 0 && (
          <div className="mt-3 flex items-center gap-2">
            <span className="text-xs text-cyan font-mono">{project.candidate_flags.length} candidate flags</span>
          </div>
        )}

        {project.last_observation_severity && project.last_observation_severity !== 'info' && (
          <div className="mt-2 flex items-center gap-1">
            <span className={`text-xs font-mono ${
              project.last_observation_severity === 'critical' ? 'text-danger' : 'text-amber'
            }`}>
              Observer: {project.last_observation_severity}
            </span>
          </div>
        )}
      </div>
    </Link>
  );
}