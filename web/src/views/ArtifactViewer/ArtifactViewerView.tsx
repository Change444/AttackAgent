import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { fetchArtifacts } from '../../api/artifacts';
import LoadingSpinner from '../../components/shared/LoadingSpinner';
import EmptyState from '../../components/shared/EmptyState';

interface ArtifactEvent {
  event_id: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

export default function ArtifactViewerView() {
  const { id } = useParams<{ id: string }>();
  const [artifacts, setArtifacts] = useState<ArtifactEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    fetchArtifacts(id)
      .then(setArtifacts)
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <LoadingSpinner />;
  if (!id) return <EmptyState message="Select a project to view artifacts" />;

  return (
    <div className="space-y-4">
      {artifacts.length === 0 ? (
        <EmptyState message="No artifacts found" />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 animate-fade-in">
          {artifacts.map((art) => {
            const payload = art.payload;
            const name = (payload.artifact_name as string) || (payload.name as string) || 'unnamed';
            const kind = (payload.artifact_kind as string) || (payload.kind as string) || 'unknown';

            return (
              <div key={art.event_id} className="bg-base-800 rounded-lg border border-base-600/30 p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-semibold text-base-50 font-mono">{name}</span>
                  <span className="text-xs bg-base-700/50 px-2 py-0.5 rounded text-slate font-mono">{kind}</span>
                </div>
                <div className="text-xs text-slate-dark font-mono">{art.event_id.slice(0, 12)}</div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}