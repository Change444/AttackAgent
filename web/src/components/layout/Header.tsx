import { useLocation, useParams } from 'react-router-dom';

const PATH_LABELS: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/reviews': 'Review Queue',
};

const PROJECT_PATH_LABELS: Record<string, string> = {
  '/projects/:id': 'Project Workspace',
  '/projects/:id/graph': 'Knowledge Graph',
  '/projects/:id/team': 'Team Board',
  '/projects/:id/ideas': 'Idea Board',
  '/projects/:id/memory': 'Memory Board',
  '/projects/:id/observer': 'Observer Panel',
  '/projects/:id/flags': 'Candidate Flags',
  '/projects/:id/artifacts': 'Artifact Viewer',
  '/projects/:id/replay': 'Replay Timeline',
};

export default function Header() {
  const location = useLocation();
  const { id } = useParams<{ id: string }>();

  let label = PATH_LABELS[location.pathname];
  if (!label && id) {
    // Match project-scoped routes
    const projectPath = location.pathname.replace(id, ':id');
    label = PROJECT_PATH_LABELS[projectPath];
  }
  if (!label) label = 'Dashboard';

  return (
    <header className="fixed top-0 left-56 right-0 h-12 bg-base-800/80 backdrop-blur-sm border-b border-base-600/30 z-30">
      <div className="flex items-center justify-between px-6 h-full">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-base-50">{label}</span>
          {id && <span className="text-xs text-slate-dark font-mono">[{id}]</span>}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-dark font-mono">
            {new Date().toLocaleTimeString()}
          </span>
        </div>
      </div>
    </header>
  );
}