import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { fetchCandidateFlags } from '../../api/candidate-flags';
import LoadingSpinner from '../../components/shared/LoadingSpinner';
import EmptyState from '../../components/shared/EmptyState';

interface FlagEvent {
  event_id: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

export default function CandidateFlagPanelView() {
  const { id } = useParams<{ id: string }>();
  const [flags, setFlags] = useState<FlagEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    fetchCandidateFlags(id)
      .then(setFlags)
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <LoadingSpinner />;
  if (!id) return <EmptyState message="Select a project to view flags" />;

  return (
    <div className="space-y-4">
      {flags.length === 0 ? (
        <EmptyState message="No candidate flags found" />
      ) : (
        <div className="space-y-3 animate-fade-in">
          {flags.map((flag) => {
            const payload = flag.payload;
            const flagValue = (payload.flag_value as string) || (payload.value as string) || 'unknown';
            const confidence = (payload.confidence as number) || 0;
            const evidenceRefs = (payload.evidence_refs as string[]) || [];

            return (
              <div key={flag.event_id} className="bg-base-800 rounded-lg border border-cyan/30 p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-mono font-semibold text-cyan">{flagValue}</span>
                    <span className="text-xs text-slate-dark font-mono">conf: {confidence.toFixed(2)}</span>
                  </div>
                  <span className="text-xs text-slate-dark font-mono">{flag.event_id.slice(0, 12)}</span>
                </div>

                {/* Evidence chain */}
                {evidenceRefs.length > 0 && (
                  <div className="mt-3">
                    <p className="text-xs text-slate-dark mb-1">Evidence Chain:</p>
                    <div className="flex gap-2 flex-wrap">
                      {evidenceRefs.map((ref) => (
                        <span key={ref} className="text-xs bg-base-700/50 px-2 py-1 rounded text-slate font-mono border border-base-600/20">
                          {ref.slice(0, 16)}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}