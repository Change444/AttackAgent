import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { fetchGraph } from '../../api/projects';
import type { MaterializedState } from '../../api/types';
import LoadingSpinner from '../../components/shared/LoadingSpinner';
import EmptyState from '../../components/shared/EmptyState';
import { KIND_LABELS, KIND_COLORS } from '../../utils/constants';

export default function GraphView() {
  const { id } = useParams<{ id: string }>();
  const [graph, setGraph] = useState<MaterializedState | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    fetchGraph(id)
      .then(setGraph)
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <LoadingSpinner />;
  if (!id) return <EmptyState message="Select a project to view graph" />;
  if (!graph) return <EmptyState message="No graph data available" />;

  return (
    <div className="space-y-4">
      {/* Node counts */}
      <div className="grid grid-cols-4 gap-3">
        <div className="bg-base-800 rounded-lg border border-cyan/30 p-3 text-center">
          <p className="text-xs text-cyan-dark">Fact Nodes</p>
          <p className="text-lg text-cyan font-mono font-bold">{graph.facts.length}</p>
        </div>
        <div className="bg-base-800 rounded-lg border border-amber/30 p-3 text-center">
          <p className="text-xs text-amber-dark">Idea Nodes</p>
          <p className="text-lg text-amber font-mono font-bold">{graph.ideas.length}</p>
        </div>
        <div className="bg-base-800 rounded-lg border border-base-600/30 p-3 text-center">
          <p className="text-xs text-slate-dark">Solver Nodes</p>
          <p className="text-lg text-base-50 font-mono font-bold">{graph.sessions.length}</p>
        </div>
        <div className="bg-base-800 rounded-lg border border-base-600/30 p-3 text-center">
          <p className="text-xs text-slate-dark">Packet Nodes</p>
          <p className="text-lg text-base-50 font-mono font-bold">{graph.packets.length}</p>
        </div>
      </div>

      {/* Fact list */}
      <div className="bg-base-800 rounded-lg border border-base-600/30 p-4">
        <h3 className="text-xs text-cyan font-mono font-semibold mb-3">Fact Nodes</h3>
        <div className="space-y-2 max-h-48 overflow-y-auto">
          {graph.facts.map((f) => (
            <div key={f.entry_id} className="flex items-center gap-2 text-xs">
              <span className={`px-2 py-0.5 rounded font-mono ${KIND_COLORS[f.kind]}`}>{KIND_LABELS[f.kind]}</span>
              <span className="text-base-50 truncate">{f.content}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Idea list */}
      <div className="bg-base-800 rounded-lg border border-base-600/30 p-4">
        <h3 className="text-xs text-amber font-mono font-semibold mb-3">Idea Nodes</h3>
        <div className="space-y-2 max-h-48 overflow-y-auto">
          {graph.ideas.map((i) => (
            <div key={i.idea_id} className="flex items-center gap-2 text-xs">
              <span className="text-amber font-mono">{i.idea_id.slice(0, 8)}</span>
              <span className="text-base-50 truncate">{i.description}</span>
              <span className="text-slate-dark">[{i.status}]</span>
            </div>
          ))}
        </div>
      </div>

      {/* Solver list */}
      <div className="bg-base-800 rounded-lg border border-base-600/30 p-4">
        <h3 className="text-xs text-slate font-mono font-semibold mb-3">Solver Nodes</h3>
        <div className="space-y-2 max-h-48 overflow-y-auto">
          {graph.sessions.map((s) => (
            <div key={s.solver_id} className="flex items-center gap-2 text-xs">
              <span className="text-base-50 font-mono">{s.solver_id.slice(0, 8)}</span>
              <span className="text-slate-dark">{s.profile}</span>
              <span className="text-amber">[{s.status}]</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}