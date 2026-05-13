import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { fetchProjectMemory } from '../../api/memory';
import type { MemoryEntry, MemoryKind } from '../../api/types';
import { KIND_LABELS, KIND_COLORS } from '../../utils/constants';
import LoadingSpinner from '../../components/shared/LoadingSpinner';
import EmptyState from '../../components/shared/EmptyState';

const KINDS: MemoryKind[] = ['fact', 'credential', 'endpoint', 'failure_boundary', 'hint', 'session_state'];

export default function MemoryBoardView() {
  const { id } = useParams<{ id: string }>();
  const [memory, setMemory] = useState<MemoryEntry[]>([]);
  const [kindFilter, setKindFilter] = useState<string>('all');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    fetchProjectMemory(id)
      .then(setMemory)
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <LoadingSpinner />;
  if (!id) return <EmptyState message="Select a project to view memory" />;

  const filtered = kindFilter === 'all' ? memory : memory.filter((m) => m.kind === kindFilter);

  return (
    <div className="space-y-4">
      {/* Kind filter */}
      <div className="flex gap-1">
        <button
          onClick={() => setKindFilter('all')}
          className={`px-3 py-1.5 rounded text-xs font-mono font-medium transition-colors ${
            kindFilter === 'all' ? 'bg-amber/20 text-amber border border-amber/30' : 'bg-base-800 text-slate-dark hover:text-slate'
          }`}
        >
          All ({memory.length})
        </button>
        {KINDS.map((k) => (
          <button
            key={k}
            onClick={() => setKindFilter(k)}
            className={`px-3 py-1.5 rounded text-xs font-mono font-medium transition-colors ${
              kindFilter === k ? 'bg-amber/20 text-amber border border-amber/30' : 'bg-base-800 text-slate-dark hover:text-slate'
            }`}
          >
            {KIND_LABELS[k]} ({memory.filter((m) => m.kind === k).length})
          </button>
        ))}
      </div>

      {/* Memory entries */}
      {filtered.length === 0 ? (
        <EmptyState message="No memory entries" />
      ) : (
        <div className="space-y-2 animate-fade-in">
          {filtered.map((entry) => (
            <div key={entry.entry_id} className="bg-base-800 rounded border border-base-600/30 p-3">
              <div className="flex items-center justify-between mb-1">
                <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-medium ${KIND_COLORS[entry.kind]}`}>
                  {KIND_LABELS[entry.kind]}
                </span>
                <span className="text-xs text-slate-dark font-mono">conf: {entry.confidence.toFixed(1)}</span>
              </div>
              <p className="text-sm text-base-50">{entry.content}</p>
              {entry.evidence_refs.length > 0 && (
                <div className="mt-2 flex gap-2 flex-wrap">
                  {entry.evidence_refs.map((ref) => (
                    <span key={ref} className="text-xs text-slate-dark font-mono bg-base-700/50 px-1.5 py-0.5 rounded">{ref.slice(0, 12)}</span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}