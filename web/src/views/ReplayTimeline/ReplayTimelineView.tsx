import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { fetchReplayTimeline } from '../../api/replay';
import type { ReplayStep } from '../../api/types';
import LoadingSpinner from '../../components/shared/LoadingSpinner';
import EmptyState from '../../components/shared/EmptyState';

export default function ReplayTimelineView() {
  const { id } = useParams<{ id: string }>();
  const [steps, setSteps] = useState<ReplayStep[]>([]);
  const [currentStep, setCurrentStep] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    fetchReplayTimeline(id)
      .then(setSteps)
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <LoadingSpinner />;
  if (!id) return <EmptyState message="Select a project to view replay" />;

  const handleStep = (direction: number) => {
    setCurrentStep((prev) => Math.max(0, Math.min(steps.length - 1, prev + direction)));
  };

  if (steps.length === 0) return <EmptyState message="No replay data available" />;

  const step = steps[currentStep];
  const state = step.state_summary;

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex items-center gap-3 bg-base-800 rounded-lg border border-base-600/30 p-3">
        <button onClick={() => setCurrentStep(0)} className="px-3 py-1.5 rounded text-xs text-slate-dark bg-base-700 hover:text-slate">Reset</button>
        <button onClick={() => handleStep(-1)} className="px-3 py-1.5 rounded text-xs text-slate bg-base-700 hover:text-slate">Prev</button>
        <span className="text-xs text-amber font-mono">Step {currentStep + 1} / {steps.length}</span>
        <button onClick={() => handleStep(1)} className="px-3 py-1.5 rounded text-xs text-slate bg-base-700 hover:text-slate">Next</button>
      </div>

      {/* Current step detail */}
      <div className="bg-base-800 rounded-lg border border-amber/30 p-4 animate-fade-in">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-xs text-amber font-mono font-semibold">{step.event_type}</span>
          </div>
          <span className="text-xs text-slate-dark font-mono">{step.timestamp}</span>
        </div>

        {/* Explanation */}
        <div className="mb-3">
          <p className="text-xs text-slate-dark mb-1">Explanation</p>
          <p className="text-sm text-base-50">{step.explanation}</p>
        </div>

        {/* State snapshot */}
        {state && (
          <div className="grid grid-cols-4 gap-2">
            <div className="bg-base-700/50 rounded p-2 text-center">
              <p className="text-xs text-slate-dark">Status</p>
              <p className="text-xs text-base-50 font-mono">{state.status || '-'}</p>
            </div>
            <div className="bg-base-700/50 rounded p-2 text-center">
              <p className="text-xs text-slate-dark">Facts</p>
              <p className="text-xs text-cyan font-mono">{state.fact_count}</p>
            </div>
            <div className="bg-base-700/50 rounded p-2 text-center">
              <p className="text-xs text-slate-dark">Ideas</p>
              <p className="text-xs text-amber font-mono">{state.idea_count}</p>
            </div>
            <div className="bg-base-700/50 rounded p-2 text-center">
              <p className="text-xs text-slate-dark">Solvers</p>
              <p className="text-xs text-base-50 font-mono">{state.solver_count}</p>
            </div>
          </div>
        )}
      </div>

      {/* Timeline strip */}
      <div className="bg-base-800 rounded-lg border border-base-600/30 p-3 overflow-x-auto">
        <div className="flex gap-1">
          {steps.map((s, idx) => (
            <button
              key={idx}
              onClick={() => setCurrentStep(idx)}
              className={`w-2 h-8 rounded transition-colors ${
                idx === currentStep ? 'bg-amber' : idx < currentStep ? 'bg-cyan/40' : 'bg-base-600/40'
              }`}
              title={`${idx}: ${s.event_type}`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}