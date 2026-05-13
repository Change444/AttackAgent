import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { fetchProjectSolvers } from '../../api/solvers';
import type { SolverSession } from '../../api/types';
import StatusBadge from '../../components/shared/StatusBadge';
import LoadingSpinner from '../../components/shared/LoadingSpinner';
import EmptyState from '../../components/shared/EmptyState';

export default function TeamBoardView() {
  const { id } = useParams<{ id: string }>();
  const [solvers, setSolvers] = useState<SolverSession[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    fetchProjectSolvers(id)
      .then(setSolvers)
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <LoadingSpinner />;
  if (!id) return <EmptyState message="Select a project to view team" />;

  return (
    <div className="space-y-4">
      {solvers.length === 0 ? (
        <EmptyState message="No solver sessions" />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 animate-fade-in">
          {solvers.map((solver) => (
            <div key={solver.solver_id} className="bg-base-800 rounded-lg border border-base-600/30 p-4">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <p className="text-sm font-semibold text-base-50 font-mono">{solver.solver_id}</p>
                  <p className="text-xs text-slate-dark">Profile: {solver.profile}</p>
                </div>
                <StatusBadge status={solver.status} domain="solver" />
              </div>

              {/* Budget bar */}
              <div className="mb-3">
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-slate-dark">Budget</span>
                  <span className="text-base-50 font-mono">{solver.budget_remaining.toFixed(2)}</span>
                </div>
                <div className="h-1.5 bg-base-700 rounded-full">
                  <div className="h-1.5 bg-amber/60 rounded-full" style={{ width: `${Math.max(0, Math.min(100, solver.budget_remaining))}%` }} />
                </div>
              </div>

              {/* Details */}
              <div className="space-y-1 text-xs text-slate-dark font-mono">
                {solver.active_idea_id && <div>Active Idea: {solver.active_idea_id.slice(0, 8)}</div>}
                {solver.scratchpad_summary && (
                  <div className="text-slate truncate">{solver.scratchpad_summary}</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}