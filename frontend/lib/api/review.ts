import { apiDelete, apiGet, apiPatch, apiPost, buildQuery } from "@/lib/api/client";
import type {
  LinkAlert,
  LinkBlock,
  LinkCandidate,
  LinkRow,
  ReviewBatchDecisionResponse,
  ReviewChange,
  ReviewEditApplyResponse,
  ReviewEditPreviewResponse,
  ReviewSummary,
} from "@/lib/types";

export async function getReviewSummary() {
  return apiGet<ReviewSummary>("/review/summary");
}

export async function listReviewChanges(params: { review_status: string; limit?: number; offset?: number; source_id?: number | null }) {
  return apiGet<ReviewChange[]>(`/review/changes${buildQuery(params)}`);
}

export async function getReviewChange(changeId: number) {
  return apiGet<ReviewChange>(`/review/changes/${changeId}`);
}

export async function markReviewChangeViewed(changeId: number, payload: { viewed: boolean; note?: string | null }) {
  return apiPatch<ReviewChange>(`/review/changes/${changeId}/views`, payload);
}

export async function decideReviewChange(changeId: number, payload: { decision: "approve" | "reject"; note?: string | null }) {
  return apiPost(`/review/changes/${changeId}/decisions`, payload);
}

export async function batchDecideReviewChanges(payload: { ids: number[]; decision: "approve" | "reject"; note?: string | null }) {
  return apiPost<ReviewBatchDecisionResponse>("/review/changes/batch/decisions", payload);
}

export async function previewReviewChangeEvidence(changeId: number, side: "before" | "after") {
  return apiGet<{ preview_text?: string; filename?: string; event_count?: number; truncated?: boolean; events?: Array<{ summary?: string | null; dtstart?: string | null; location?: string | null }> }>(`/review/changes/${changeId}/evidence/${side}/preview`);
}

export async function previewReviewEdit(payload: { mode: "proposal" | "canonical"; target: { change_id?: number; event_uid?: string | null }; patch: { due_at: string; title?: string | null; course_label?: string | null }; reason?: string | null }) {
  return apiPost<ReviewEditPreviewResponse>("/review/edits/preview", payload);
}

export async function applyReviewEdit(payload: { mode: "proposal" | "canonical"; target: { change_id?: number; event_uid?: string | null }; patch: { due_at: string; title?: string | null; course_label?: string | null }; reason?: string | null }) {
  return apiPost<ReviewEditApplyResponse>("/review/edits", payload);
}

export async function listLinkCandidates(params: { status: string; limit?: number; offset?: number; source_id?: number | null }) {
  return apiGet<LinkCandidate[]>(`/review/link-candidates${buildQuery(params)}`);
}

export async function batchDecideLinkCandidates(payload: { ids: number[]; decision: "approve" | "reject"; note?: string | null }) {
  return apiPost("/review/link-candidates/batch/decisions", payload);
}

export async function decideLinkCandidate(candidateId: number, payload: { decision: "approve" | "reject"; note?: string | null }) {
  return apiPost(`/review/link-candidates/${candidateId}/decisions`, payload);
}

export async function listReviewLinks(params: { limit?: number; offset?: number }) {
  return apiGet<LinkRow[]>(`/review/links${buildQuery(params)}`);
}

export async function relinkObservation(payload: { source_id: number; external_event_id: string; entity_uid: string; clear_block: boolean; note?: string | null }) {
  return apiPost("/review/links/relink", payload);
}

export async function deleteReviewLink(linkId: number, params?: { block?: boolean; note?: string }) {
  const query = buildQuery({ block: params?.block, note: params?.note });
  return apiDelete(`/review/links/${linkId}${query}`);
}

export async function listLinkAlerts(params: { status: string; limit?: number; offset?: number }) {
  return apiGet<LinkAlert[]>(`/review/link-alerts${buildQuery(params)}`);
}

export async function batchDecideLinkAlerts(payload: { ids: number[]; decision: "dismiss" | "mark_safe"; note?: string | null }) {
  return apiPost("/review/link-alerts/batch/decisions", payload);
}

export async function decideLinkAlert(alertId: number, action: "dismiss" | "mark-safe", payload: { note?: string | null }) {
  return apiPost(`/review/link-alerts/${alertId}/${action}`, payload);
}

export async function listLinkBlocks(params: { limit?: number; offset?: number; source_id?: number | null }) {
  return apiGet<LinkBlock[]>(`/review/link-candidates/blocks${buildQuery(params)}`);
}

export async function deleteLinkBlock(blockId: number) {
  return apiDelete(`/review/link-candidates/blocks/${blockId}`);
}
