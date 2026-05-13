import { apiGet, apiPost } from './client';
import type { ReviewRequest } from './types';

export function fetchProjectReviews(projectId: string): Promise<ReviewRequest[]> {
  return apiGet<ReviewRequest[]>(`/projects/${projectId}/reviews`);
}

export function fetchAllReviews(status?: string): Promise<ReviewRequest[]> {
  const query = status ? `?status=${status}` : '';
  return apiGet<ReviewRequest[]>(`/reviews${query}`);
}

export function approveReview(requestId: string, projectId: string, reason: string): Promise<ReviewRequest> {
  return apiPost<ReviewRequest>(`/reviews/${requestId}/approve`, { project_id: projectId, reason });
}

export function rejectReview(requestId: string, projectId: string, reason: string): Promise<ReviewRequest> {
  return apiPost<ReviewRequest>(`/reviews/${requestId}/reject`, { project_id: projectId, reason });
}

export function modifyReview(requestId: string, projectId: string, reason: string, modified_params: string): Promise<ReviewRequest> {
  return apiPost<ReviewRequest>(`/reviews/${requestId}/modify`, { project_id: projectId, reason, modified_params });
}