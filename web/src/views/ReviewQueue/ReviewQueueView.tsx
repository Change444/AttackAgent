import { useState, useEffect } from 'react';
import { fetchAllReviews, approveReview, rejectReview } from '../../api/reviews';
import type { ReviewRequest } from '../../api/types';
import StatusBadge from '../../components/shared/StatusBadge';
import LoadingSpinner from '../../components/shared/LoadingSpinner';
import EmptyState from '../../components/shared/EmptyState';
import { ConfirmModal } from '../../components/shared/Modal';

export default function ReviewQueueView() {
  const [reviews, setReviews] = useState<ReviewRequest[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>('pending');
  const [loading, setLoading] = useState(true);
  const [confirmAction, setConfirmAction] = useState<{ title: string; message: string; onConfirm: () => void } | null>(null);
  const [actionResult, setActionResult] = useState<string | null>(null);

  const loadReviews = () => {
    setLoading(true);
    fetchAllReviews(statusFilter)
      .then(setReviews)
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadReviews(); }, [statusFilter]);

  const handleApprove = (review: ReviewRequest) => {
    setConfirmAction({
      title: 'Approve Review',
      message: `Approve "${review.title}"? The proposed action will be executed.`,
      onConfirm: () => {
        approveReview(review.request_id, review.project_id, 'Approved via Console')
          .then(() => { loadReviews(); setActionResult('Review approved'); setConfirmAction(null); })
          .catch((e) => { setActionResult(`Error: ${e.message}`); setConfirmAction(null); });
      },
    });
  };

  const handleReject = (review: ReviewRequest) => {
    setConfirmAction({
      title: 'Reject Review',
      message: `Reject "${review.title}"? The action will be blocked and a failure boundary recorded.`,
      onConfirm: () => {
        rejectReview(review.request_id, review.project_id, 'Rejected via Console')
          .then(() => { loadReviews(); setActionResult('Review rejected'); setConfirmAction(null); })
          .catch((e) => { setActionResult(`Error: ${e.message}`); setConfirmAction(null); });
      },
    });
  };

  if (loading) return <LoadingSpinner />;

  const filters = ['pending', 'approved', 'rejected', 'modified', 'expired'];

  return (
    <div className="space-y-4">
      {/* Action result toast */}
      {actionResult && (
        <div className="bg-base-800 rounded-lg border border-cyan/30 p-3 flex items-center justify-between animate-fade-in">
          <span className="text-xs text-cyan font-mono">{actionResult}</span>
          <button onClick={() => setActionResult(null)} className="text-xs text-slate-dark">Dismiss</button>
        </div>
      )}

      {/* Filter tabs */}
      <div className="flex gap-1">
        {filters.map((f) => (
          <button
            key={f}
            onClick={() => setStatusFilter(f)}
            className={`px-3 py-1.5 rounded text-xs font-mono font-medium transition-colors ${
              statusFilter === f ? 'bg-amber/20 text-amber border border-amber/30' : 'bg-base-800 text-slate-dark hover:text-slate'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Review list */}
      {reviews.length === 0 ? (
        <EmptyState message={`No ${statusFilter} reviews`} />
      ) : (
        <div className="space-y-3 animate-fade-in">
          {reviews.map((review) => (
            <div key={review.request_id} className="bg-base-800 rounded-lg border border-base-600/30 hover:border-amber/30 transition-colors p-4">
              <div className="flex items-center justify-between mb-2">
                <div>
                  <h3 className="text-sm font-semibold text-base-50">{review.title}</h3>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-xs text-slate-dark font-mono">{review.action_type}</span>
                    <StatusBadge status={review.risk_level} domain="risk" />
                    <span className="text-xs text-slate-dark font-mono">Project: {review.project_id}</span>
                  </div>
                </div>
                <StatusBadge status={review.status} domain="review" />
              </div>
              <p className="text-xs text-slate mt-2">{review.description}</p>

              {/* Proposed action details */}
              {review.proposed_action && (
                <div className="mt-3 bg-base-700/30 rounded p-2">
                  <p className="text-xs text-slate-dark mb-1">Proposed Action:</p>
                  <p className="text-xs text-amber font-mono">{review.proposed_action}</p>
                </div>
              )}

              {/* Action buttons for pending reviews */}
              {review.status === 'pending' && (
                <div className="mt-3 flex gap-2">
                  <button onClick={() => handleApprove(review)} className="px-3 py-1.5 rounded text-xs font-medium bg-cyan/20 text-cyan hover:bg-cyan/30 border border-cyan/30 transition-colors">
                    Approve
                  </button>
                  <button onClick={() => handleReject(review)} className="px-3 py-1.5 rounded text-xs font-medium bg-danger/20 text-danger hover:bg-danger/30 border border-danger/30 transition-colors">
                    Reject
                  </button>
                </div>
              )}

              {/* Causal linkage */}
              <div className="mt-3 flex gap-4 text-xs text-slate-dark font-mono">
                <span>ID: {review.request_id}</span>
                {review.evidence_refs.length > 0 && <span>Evidence: {review.evidence_refs.length} refs</span>}
                {review.decided_by && <span>Decided by: {review.decided_by}</span>}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Confirm modal */}
      {confirmAction && (
        <ConfirmModal
          title={confirmAction.title}
          message={confirmAction.message}
          onConfirm={confirmAction.onConfirm}
          onCancel={() => setConfirmAction(null)}
          danger={confirmAction.title.includes('Reject')}
          confirmLabel={confirmAction.title.includes('Reject') ? 'Reject' : 'Approve'}
        />
      )}
    </div>
  );
}