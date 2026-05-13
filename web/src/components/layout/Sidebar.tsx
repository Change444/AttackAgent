import { NavLink, useParams } from 'react-router-dom';
import { Activity, Shield, Users, Lightbulb, Database, Eye, ClipboardCheck, Flag, FileText, GitBranch, Clock } from 'lucide-react';
import { useSSEContext } from '../../context/SSEContext';

const PROJECT_NAV_ITEMS = [
  { path: '/projects/:id', label: 'Project', icon: Shield },
  { path: '/projects/:id/graph', label: 'Graph', icon: GitBranch },
  { path: '/projects/:id/team', label: 'Team', icon: Users },
  { path: '/projects/:id/ideas', label: 'Ideas', icon: Lightbulb },
  { path: '/projects/:id/memory', label: 'Memory', icon: Database },
  { path: '/projects/:id/observer', label: 'Observer', icon: Eye },
  { path: '/projects/:id/flags', label: 'Flags', icon: Flag },
  { path: '/projects/:id/artifacts', label: 'Artifacts', icon: FileText },
  { path: '/projects/:id/replay', label: 'Replay', icon: Clock },
];

const GLOBAL_NAV_ITEMS = [
  { path: '/dashboard', label: 'Dashboard', icon: Activity },
  { path: '/reviews', label: 'Reviews', icon: ClipboardCheck },
];

export default function Sidebar() {
  const { id } = useParams<{ id: string }>();
  const { connectionStatus } = useSSEContext();

  const buildPath = (template: string) => {
    if (!id) return template;
    return template.replace(':id', id);
  };

  return (
    <aside className="fixed left-0 top-0 bottom-0 w-56 bg-base-800 border-r border-base-600/30 flex flex-col z-40">
      {/* Brand */}
      <div className="px-4 py-5 border-b border-base-600/30">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-md bg-amber/20 border border-amber/40 flex items-center justify-center">
            <Shield size={16} className="text-amber" />
          </div>
          <div>
            <h1 className="text-sm font-semibold text-base-50 tracking-tight">AttackAgent</h1>
            <p className="text-xs text-slate-dark font-mono">Console v0.1</p>
          </div>
        </div>
      </div>

      {/* Amber accent line */}
      <div className="h-px bg-gradient-to-r from-amber/60 via-amber/20 to-transparent" />

      {/* Global navigation */}
      <nav className="px-2 py-2 space-y-1">
        <p className="px-3 text-xs text-slate-dark font-semibold uppercase tracking-wider mb-1">Global</p>
        {GLOBAL_NAV_ITEMS.map(({ path, label, icon: Icon }) => (
          <NavLink
            key={label}
            to={path}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-md text-xs font-medium transition-colors ${
                isActive
                  ? 'bg-amber/10 text-amber border border-amber/20'
                  : 'text-slate-dark hover:text-slate hover:bg-base-700/50'
              }`
            }
          >
            <Icon size={14} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      {/* Project navigation */}
      <div className="border-t border-base-600/30 px-2 py-2 space-y-1">
        <p className="px-3 text-xs text-slate-dark font-semibold uppercase tracking-wider mb-1">Project</p>
        {id ? (
          PROJECT_NAV_ITEMS.map(({ path, label, icon: Icon }) => (
            <NavLink
              key={label}
              to={buildPath(path)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-md text-xs font-medium transition-colors ${
                  isActive
                    ? 'bg-amber/10 text-amber border border-amber/20'
                    : 'text-slate-dark hover:text-slate hover:bg-base-700/50'
                }`
              }
            >
              <Icon size={14} />
              <span>{label}</span>
            </NavLink>
          ))
        ) : (
          <p className="px-3 text-xs text-slate-dark">Select a project from Dashboard</p>
        )}
      </div>

      {/* Status footer */}
      <div className="mt-auto px-4 py-3 border-t border-base-600/30">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${
            connectionStatus === 'open' ? 'bg-cyan animate-glow-pulse' :
            connectionStatus === 'error' ? 'bg-danger' :
            'bg-amber'
          }`} />
          <span className="text-xs text-slate-dark font-mono">
            {connectionStatus === 'open' ? 'SSE Connected' :
             connectionStatus === 'error' ? 'SSE Error' :
             connectionStatus === 'closed' ? 'SSE Disconnected' :
             'SSE Connecting...'}
          </span>
        </div>
      </div>
    </aside>
  );
}