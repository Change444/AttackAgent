import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { fetchObserverReports } from '../../api/observer';
import { SEVERITY_COLORS, INTERVENTION_COLORS } from '../../utils/constants';
import LoadingSpinner from '../../components/shared/LoadingSpinner';
import EmptyState from '../../components/shared/EmptyState';

interface ObserverReportEvent {
  event_id: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

export default function ObserverPanelView() {
  const { id } = useParams<{ id: string }>();
  const [reports, setReports] = useState<ObserverReportEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    fetchObserverReports(id)
      .then(setReports)
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <LoadingSpinner />;
  if (!id) return <EmptyState message="Select a project to view observer" />;

  return (
    <div className="space-y-4">
      {reports.length === 0 ? (
        <EmptyState message="No observer reports" />
      ) : (
        <div className="space-y-3 animate-fade-in">
          {reports.map((report) => {
            const payload = report.payload;
            const severity = (payload.severity as string) || 'info';
            const intervention = (payload.intervention_level as string) || 'observe';
            const observations = (payload.observations as Array<Record<string, string>>) || [];
            const suggestedActions = (payload.suggested_actions as string[] | undefined) || [];

            return (
              <div key={report.event_id} className="bg-base-800 rounded-lg border border-base-600/30 p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className={`text-xs font-mono font-semibold ${SEVERITY_COLORS[severity]}`}>
                      {severity}
                    </span>
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-medium ${INTERVENTION_COLORS[intervention]}`}>
                      {intervention}
                    </span>
                  </div>
                  <span className="text-xs text-slate-dark font-mono">{report.event_id.slice(0, 12)}</span>
                </div>

                {observations.length > 0 && (
                  <div className="space-y-2 mt-3">
                    {observations.map((obs, idx) => (
                      <div key={idx} className="bg-base-700/50 rounded p-2">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs text-amber font-mono">{obs.kind}</span>
                          {obs.solver_id && <span className="text-xs text-slate-dark font-mono">Solver: {obs.solver_id.slice(0, 8)}</span>}
                        </div>
                        <p className="text-xs text-base-50">{obs.description}</p>
                      </div>
                    ))}
                  </div>
                )}

                {suggestedActions.length > 0 && (
                  <div className="mt-3">
                    <p className="text-xs text-slate-dark mb-1">Suggested Actions:</p>
                    <div className="flex gap-2">
                      {suggestedActions.map((action, idx) => (
                        <span key={idx} className="text-xs bg-base-700/50 px-2 py-1 rounded text-slate font-mono">{action}</span>
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