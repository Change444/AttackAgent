import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { fetchProjectIdeas } from '../../api/ideas';
import type { IdeaEntry, IdeaStatus } from '../../api/types';
import StatusBadge from '../../components/shared/StatusBadge';
import LoadingSpinner from '../../components/shared/LoadingSpinner';
import EmptyState from '../../components/shared/EmptyState';

const IDEA_COLUMNS: IdeaStatus[] = ['pending', 'claimed', 'testing', 'verified', 'failed', 'shelved'];

export default function IdeaBoardView() {
  const { id } = useParams<{ id: string }>();
  const [ideas, setIdeas] = useState<IdeaEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    fetchProjectIdeas(id)
      .then(setIdeas)
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <LoadingSpinner />;
  if (!id) return <EmptyState message="Select a project to view ideas" />;

  const byStatus = (status: IdeaStatus) => ideas.filter((i) => i.status === status);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-6 gap-3">
        {IDEA_COLUMNS.map((status) => (
          <div key={status} className="bg-base-800 rounded-lg border border-base-600/30">
            <div className="px-3 py-2 border-b border-base-600/30 flex items-center justify-between">
              <StatusBadge status={status} domain="idea" />
              <span className="text-xs text-slate-dark font-mono">{byStatus(status).length}</span>
            </div>
            <div className="p-2 space-y-2 max-h-80 overflow-y-auto">
              {byStatus(status).length === 0 ? (
                <p className="text-xs text-slate-dark text-center py-4">-</p>
              ) : (
                byStatus(status).map((idea) => (
                  <div key={idea.idea_id} className="bg-base-700/50 rounded p-2 border border-base-600/20">
                    <p className="text-xs text-base-50">{idea.description}</p>
                    <div className="mt-1 text-xs text-slate-dark font-mono flex gap-2">
                      <span>{idea.idea_id.slice(0, 8)}</span>
                      {idea.solver_id && <span>{idea.solver_id.slice(0, 8)}</span>}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}