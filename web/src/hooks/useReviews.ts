import { useState, useEffect, useCallback } from 'react';
import { fetchProjectReviews } from '../api/reviews';
import type { ReviewRequest, SSEEvent } from '../api/types';
import { useSSEContext } from '../context/SSEContext';

export function useReviews(projectId: string) {
  const [reviews, setReviews] = useState<ReviewRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const { subscribe, unsubscribe } = useSSEContext();

  useEffect(() => {
    fetchProjectReviews(projectId)
      .then(setReviews)
      .finally(() => setLoading(false));
  }, [projectId]);

  const handleReviewCreated = useCallback((event: SSEEvent) => {
    if (event.project_id !== projectId) return;
    setReviews((prev) => [...prev, event.payload as unknown as ReviewRequest]);
  }, [projectId]);

  const handleReviewDecided = useCallback((event: SSEEvent) => {
    if (event.project_id !== projectId) return;
    setReviews((prev) => {
      const requestId = (event.payload as unknown as ReviewRequest).request_id;
      return prev.filter((r) => r.request_id !== requestId);
    });
  }, [projectId]);

  useEffect(() => {
    subscribe('review_created', handleReviewCreated);
    subscribe('review_decided', handleReviewDecided);
    return () => {
      unsubscribe('review_created', handleReviewCreated);
      unsubscribe('review_decided', handleReviewDecided);
    };
  }, [subscribe, unsubscribe, handleReviewCreated, handleReviewDecided]);

  return { reviews, loading };
}