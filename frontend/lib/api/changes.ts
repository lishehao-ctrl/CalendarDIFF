import { apiGet, apiPatch, apiPost, buildQuery } from "@/lib/api/client";
import type {
  ChangesWorkbenchSummary,
  EvidencePreviewResponse,
  LabelLearningApplyResponse,
  LabelLearningPreview,
  ChangeBatchDecisionResponse,
  ChangeItem,
  ChangeEditApplyResponse,
  ChangeEditContext,
  ChangeEditPreviewResponse,
  ChangeEditRequest,
} from "@/lib/types";

export async function getChangesSummary() {
  return apiGet<ChangesWorkbenchSummary>("/changes/summary");
}

export async function listChanges(params: {
  review_status: "pending" | "approved" | "rejected" | "all";
  review_bucket?: "initial_review" | "changes" | "all";
  intake_phase?: "baseline" | "replay" | "all";
  limit?: number;
  offset?: number;
  source_id?: number | null;
}) {
  return apiGet<ChangeItem[]>(`/changes${buildQuery(params)}`);
}

export async function getChange(changeId: number) {
  return apiGet<ChangeItem>(`/changes/${changeId}`);
}

export async function getChangeEditContext(changeId: number) {
  return apiGet<ChangeEditContext>(`/changes/${changeId}/edit-context`);
}

export async function markChangeViewed(changeId: number, payload: { viewed: boolean; note?: string | null }) {
  return apiPatch<ChangeItem>(`/changes/${changeId}/views`, payload);
}

export async function decideChange(changeId: number, payload: { decision: "approve" | "reject"; note?: string | null }) {
  return apiPost(`/changes/${changeId}/decisions`, payload);
}

export async function batchDecideChanges(payload: { ids: number[]; decision: "approve" | "reject"; note?: string | null }) {
  return apiPost<ChangeBatchDecisionResponse>("/changes/batch/decisions", payload);
}

export async function previewChangeEvidence(changeId: number, side: "before" | "after") {
  return apiGet<EvidencePreviewResponse>(`/changes/${changeId}/evidence/${side}/preview`);
}

export async function previewChangeEdit(payload: ChangeEditRequest) {
  return apiPost<ChangeEditPreviewResponse>("/changes/edits/preview", payload);
}

export async function applyChangeEdit(payload: ChangeEditRequest) {
  return apiPost<ChangeEditApplyResponse>("/changes/edits", payload);
}

export async function previewChangeLabelLearning(changeId: number) {
  return apiPost<LabelLearningPreview>(`/changes/${changeId}/label-learning/preview`);
}

export async function applyChangeLabelLearning(changeId: number, payload: { mode: "add_alias" | "create_family"; family_id?: number | null; canonical_label?: string | null }) {
  return apiPost<LabelLearningApplyResponse>(`/changes/${changeId}/label-learning`, payload);
}
