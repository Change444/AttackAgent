import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { fetchProjectStatus, pauseProject, resumeProject, addHint } from '../../api/projects';
import { fetchProjectIdeas } from '../../api/ideas';
import { fetchProjectSolvers } from '../../api/solvers';
import { fetchProjectMemory } from '../../api/memory';
import { fetchProjectReviews } from '../../api/reviews';
import { approveReview, rejectReview } from '../../api/reviews';
import type { ProjectStatusReport, IdeaEntry, SolverSession, MemoryEntry, ReviewRequest } from '../../api/types';
import StatusBadge from '../../components/shared/StatusBadge';
import LoadingSpinner from '../../components/shared/LoadingSpinner';
import { ConfirmModal } from '../../components/shared/Modal';

type Tab = 'ideas' | 'memory' | 'solvers' | 'reviews';

export default function ProjectWorkspaceView() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<ProjectStatusReport | null>(null);
  const [ideas, setIdeas] = useState<IdeaEntry[]>([]);
  const [solvers, setSolvers] = useState<SolverSession[]>([]);
  const [memory, setMemory] = useState<MemoryEntry[]>([]);
  const [reviews, setReviews] = useState<ReviewRequest[]>([]);
  const [activeTab, setActiveTab] = useState<Tab>('ideas');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<{ title: string; message: string; onConfirm: () => void } | null>(null);
  const [hintText, setHintText] = useState('');
  const [showHintInput, setShowHintInput] = useState(false);
  const [actionResult, setActionResult] = useState<string | null>(null);

  const loadData = useCallback(() => {
    if (!id) return;
    Promise.all([
      fetchProjectStatus(id),
      fetchProjectIdeas(id),
      fetchProjectSolvers(id),
      fetchProjectMemory(id),
      fetchProjectReviews(id),
    ])
      .then(([p, i, s, m, r]) => {
        setProject(p);
        setIdeas(i);
        setSolvers(s);
        setMemory(m);
        setReviews(r);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => { loadData(); }, [loadData]);

  const handlePause = () => {
    if (!id) return;
    setConfirmAction({
      title: 'Pause Project',
      message: 'Are you sure you want to pause this project? The scheduler will stop.',
      onConfirm: () => {
        pauseProject(id).then(() => { loadData(); setActionResult('Project paused'); setConfirmAction(null); }).catch((e) => { setActionResult(`Error: ${e.message}`); setConfirmAction(null); });
      },
    });
  };

  const handleResume = () => {
    if (!id) return;
    setConfirmAction({
      title: 'Resume Project',
      message: 'Resume the paused project? The scheduler will restart.',
      onConfirm: () => {
        resumeProject(id).then(() => { loadData(); setActionResult('Project resumed'); setConfirmAction(null); }).catch((e) => { setActionResult(`Error: ${e.message}`); setConfirmAction(null); });
      },
    });
  };

  const handleAddHint = () => {
    if (!id || !hintText.trim()) return;
    addHint(id, hintText.trim()).then(() => { setHintText(''); setShowHintInput(false); loadData(); setActionResult('Hint added'); }).catch((e) => setActionResult(`Error: ${e.message}`));
  };

  const handleApproveReview = (requestId: string) => {
    if (!id) return;
    setConfirmAction({
      title: 'Approve Review',
      message: 'Approve this review request? The action will be executed.',
      onConfirm: () => {
        approveReview(requestId, id, 'Approved via Console').then(() => { loadData(); setActionResult('Review approved'); setConfirmAction(null); }).catch((e) => { setActionResult(`Error: ${e.message}`); setConfirmAction(null); });
      },
    });
  };

  const handleRejectReview = (requestId: string) => {
    if (!id) return;
    setConfirmAction({
      title: 'Reject Review',
      message: 'Reject this review request? The action will be blocked and a failure boundary recorded.',
      onConfirm: () => {
        rejectReview(requestId, id, 'Rejected via Console').then(() => { loadData(); setActionResult('Review rejected'); setConfirmAction(null); }).catch((e) => { setActionResult(`Error: ${e.message}`); setConfirmAction(null); });
      },
    });
  };

  if (loading) return <LoadingSpinner />;
  if (error || !project) return <div className="text-danger text-sm">{error || 'Project not found'}</div>;

  const tabs: { key: Tab; label: string }[] = [
    { key: 'ideas', label: 'Ideas' },
    { key: 'memory', label: 'Memory' },
    { key: 'solvers', label: 'Solvers' },
    { key: 'reviews', label: 'Reviews' },
  ];

  return (
    <div className="space-y-4">
      {/* Action result toast */}
      {actionResult && (
        <div className="bg-base-800 rounded-lg border border-cyan/30 p-3 flex items-center justify-between animate-fade-in">
          <span className="text-xs text-cyan font-mono">{actionResult}</span>
          <button onClick={() => setActionResult(null)} className="text-xs text-slate-dark">Dismiss</button>
        </div>
      )}

      {/* Project Header with Lifecycle Controls */}
      <div className="bg-base-800 rounded-lg border border-base-600/30 p-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-base-50 font-mono">{project.project_id}</h2>
            <p className="text-sm text-slate-dark">{project.challenge_id}</p>
          </div>
          <div className="flex items-center gap-3">
            <StatusBadge status={project.status} domain="project" />
            {/* Lifecycle controls */}
            <div className="flex gap-2">
              {project.status === 'running' && (
                <button onClick={handlePause} className="px-3 py-1.5 rounded text-xs font-medium bg-amber/20 text-amber hover:bg-amber/30 border border-amber/30 transition-colors">
                  Pause
                </button>
              )}
              {project.status === 'paused' && (
                <button onClick={handleResume} className="px-3 py-1.5 rounded text-xs font-medium bg-cyan/20 text-cyan hover:bg-cyan/30 border border-cyan/30 transition-colors">
                  Resume
                </button>
              )}
              <button onClick={() => setShowHintInput(!showHintInput)} className="px-3 py-1.5 rounded text-xs font-medium bg-base-700 text-slate hover:text-base-50 transition-colors">
                Add Hint
              </button>
            </div>
          </div>
        </div>

        {/* Hint input */}
        {showHintInput && (
          <div className="mt-3 flex gap-2 animate-fade-in">
            <input
              type="text"
              value={hintText}
              onChange={(e) => setHintText(e.target.value)}
              placeholder="Enter hint text..."
              className="flex-1 bg-base-700/50 border border-base-600/30 rounded px-3 py-2 text-sm text-base-50 placeholder-slate-dark font-mono focus:border-amber/40 focus:outline-none"
            />
            <button onClick={handleAddHint} className="px-4 py-2 rounded text-xs font-medium bg-amber text-base-900 hover:bg-amber-light transition-colors">
              Submit Hint
            </button>
          </div>
        )}

        <div className="grid grid-cols-4 gap-3 mt-3">
          <div className="text-center">
            <p className="text-xs text-slate-dark">Solvers</p>
            <p className="text-base-50 font-mono font-semibold">{project.solver_count}</p>
          </div>
          <div className="text-center">
            <p className="text-xs text-slate-dark">Ideas</p>
            <p className="text-base-50 font-mono font-semibold">{project.idea_count}</p>
          </div>
          <div className="text-center">
            <p className="text-xs text-slate-dark">Facts</p>
            <p className="text-base-50 font-mono font-semibold">{project.fact_count}</p>
          </div>
          <div className="text-center">
            <p className="text-xs text-amber">Pending Reviews</p>
            <p className="text-amber font-mono font-semibold">{project.pending_review_count}</p>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-base-600/30">
        {tabs.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`px-4 py-2 text-xs font-medium transition-colors ${
              activeTab === key
                ? 'text-amber border-b-2 border-amber'
                : 'text-slate-dark hover:text-slate'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="animate-fade-in">
        {activeTab === 'ideas' && (
          <div className="space-y-2">
            {ideas.length === 0 ? <p className="text-sm text-slate-dark">No ideas yet.</p> : null}
            {ideas.map((idea) => (
              <div key={idea.idea_id} className="bg-base-800 rounded border border-base-600/30 p-3">
                <div className="flex items-center justify-between">
                  <p className="text-sm text-base-50">{idea.description}</p>
                  <StatusBadge status={idea.status} domain="idea" />
                </div>
                <div className="mt-2 flex gap-3 text-xs text-slate-dark font-mono">
                  <span>ID: {idea.idea_id}</span>
                  {idea.solver_id && <span>Solver: {idea.solver_id}</span>}
                  <span>Pri: {idea.priority}</span>
                </div>
              </div>
            ))}
          </div>
        )}
        {activeTab === 'memory' && (
          <div className="space-y-2">
            {memory.length === 0 ? <p className="text-sm text-slate-dark">No memory entries yet.</p> : null}
            {memory.map((entry) => (
              <div key={entry.entry_id} className="bg-base-800 rounded border border-base-600/30 p-3">
                <div className="flex items-center justify-between mb-1">
                  <StatusBadge status={entry.kind} domain="risk" />
                  <span className="text-xs text-slate-dark font-mono">{entry.confidence.toFixed(1)} confidence</span>
                </div>
                <p className="text-sm text-base-50">{entry.content}</p>
              </div>
            ))}
          </div>
        )}
        {activeTab === 'solvers' && (
          <div className="space-y-2">
            {solvers.length === 0 ? <p className="text-sm text-slate-dark">No solver sessions yet.</p> : null}
            {solvers.map((solver) => (
              <div key={solver.solver_id} className="bg-base-800 rounded border border-base-600/30 p-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-base-50 font-mono">{solver.solver_id}</p>
                    <p className="text-xs text-slate-dark">Profile: {solver.profile}</p>
                  </div>
                  <StatusBadge status={solver.status} domain="solver" />
                </div>
                <div className="mt-2 flex gap-3 text-xs text-slate-dark">
                  <span>Budget: {solver.budget_remaining.toFixed(2)}</span>
                  {solver.active_idea_id && <span>Idea: {solver.active_idea_id}</span>}
                </div>
                {/* Solver actions — freeze/stop not yet in API */}
                <div className="mt-2 flex gap-2">
                  <button disabled className="px-2 py-1 rounded text-xs text-slate-dark bg-base-700/30 cursor-not-allowed" title="API endpoint pending">
                    Freeze (pending API)
                  </button>
                  <button disabled className="px-2 py-1 rounded text-xs text-slate-dark bg-base-700/30 cursor-not-allowed" title="API endpoint pending">
                    Stop (pending API)
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
        {activeTab === 'reviews' && (
          <div className="space-y-2">
            {reviews.length === 0 ? <p className="text-sm text-slate-dark">No pending reviews.</p> : null}
            {reviews.map((review) => (
              <div key={review.request_id} className="bg-base-800 rounded border border-amber/30 p-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-amber font-semibold">{review.title}</p>
                    <p className="text-xs text-slate-dark">{review.action_type} | Risk: {review.risk_level}</p>
                  </div>
                  <StatusBadge status={review.status} domain="review" />
                </div>
                <p className="text-xs text-slate mt-2">{review.description}</p>
                {/* Review action buttons */}
                {review.status === 'pending' && (
                  <div className="mt-3 flex gap-2">
                    <button onClick={() => handleApproveReview(review.request_id)} className="px-3 py-1.5 rounded text-xs font-medium bg-cyan/20 text-cyan hover:bg-cyan/30 border border-cyan/30 transition-colors">
                      Approve
                    </button>
                    <button onClick={() => handleRejectReview(review.request_id)} className="px-3 py-1.5 rounded text-xs font-medium bg-danger/20 text-danger hover:bg-danger/30 border border-danger/30 transition-colors">
                      Reject
                    </button>
                  </div>
                )}
                {/* Causal linkage */}
                <div className="mt-2 flex gap-3 text-xs text-slate-dark font-mono">
                  <span>ID: {review.request_id}</span>
                  <span>Project: {review.project_id}</span>
                  {review.evidence_refs.length > 0 && <span>Evidence: {review.evidence_refs.length} refs</span>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Confirm modal */}
      {confirmAction && (
        <ConfirmModal
          title={confirmAction.title}
          message={confirmAction.message}
          onConfirm={confirmAction.onConfirm}
          onCancel={() => setConfirmAction(null)}
          danger={confirmAction.title.includes('Reject')}
          confirmLabel={confirmAction.title.includes('Reject') ? 'Reject' : 'Confirm'}
        />
      )}
    </div>
  );
}