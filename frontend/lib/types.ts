export type SourceHealth = {
  status: "healthy" | "attention" | "disconnected";
  message: string;
  affected_source_id: number | null;
  affected_provider: string | null;
};

export type OnboardingStatus = {
  stage: string;
  message: string;
  registered_user_id: number | null;
  first_source_id: number | null;
  source_health: SourceHealth | null;
};

export type ReviewSummary = {
  changes_pending: number;
  link_candidates_pending: number;
  link_alerts_pending: number;
  generated_at: string;
};

export type SourceRow = {
  source_id: number;
  source_kind: string;
  provider: string;
  source_key: string;
  display_name: string | null;
  is_active: boolean;
  poll_interval_seconds: number;
  last_polled_at: string | null;
  next_poll_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  created_at?: string;
  updated_at?: string;
  config: Record<string, unknown>;
  oauth_connection_status?: "connected" | "not_connected" | null;
  oauth_account_email?: string | null;
};

export type SyncStatus = {
  request_id: string;
  source_id: number;
  status: string;
  applied: boolean;
  error_code: string | null;
  error_message: string | null;
  connector_result: {
    status?: string;
    error_code?: string | null;
    error_message?: string | null;
  } | null;
};

export type ReviewChange = {
  id: number;
  event_uid: string;
  change_type: string;
  detected_at: string;
  review_status: string;
  before_json: Record<string, unknown> | null;
  after_json: Record<string, unknown> | null;
  proposal_merge_key?: string | null;
  source_id: number | null;
  proposal_sources: Array<{
    source_id: number;
    source_kind?: string | null;
    provider?: string | null;
    external_event_id?: string | null;
    confidence?: number | null;
  }>;
  viewed_at?: string | null;
  viewed_note?: string | null;
  reviewed_at?: string | null;
  review_note?: string | null;
  source_kind?: string | null;
  priority_rank?: number | null;
  priority_label?: string | null;
  notification_state?: string | null;
  deliver_after?: string | null;
  change_summary?: {
    old: {
      value_time?: string | null;
      source_label?: string | null;
      source_kind?: string | null;
      source_observed_at?: string | null;
    };
    new: {
      value_time?: string | null;
      source_label?: string | null;
      source_kind?: string | null;
      source_observed_at?: string | null;
    };
  } | null;
};

export type EvidencePreviewEvent = {
  uid?: string | null;
  summary?: string | null;
  dtstart?: string | null;
  dtend?: string | null;
  location?: string | null;
  description?: string | null;
  url?: string | null;
};

export type EvidencePreviewStructuredItem = {
  uid?: string | null;
  title?: string | null;
  course_label?: string | null;
  start_at?: string | null;
  end_at?: string | null;
  location?: string | null;
  description?: string | null;
  url?: string | null;
  sender?: string | null;
  snippet?: string | null;
  internal_date?: string | null;
  thread_id?: string | null;
};

export type EvidencePreviewResponse = {
  side: "before" | "after";
  content_type: string;
  truncated: boolean;
  filename: string;
  provider?: string | null;
  structured_kind?: "ics_event" | "gmail_event" | "generic";
  structured_items: EvidencePreviewStructuredItem[];
  event_count: number;
  events: EvidencePreviewEvent[];
  preview_text?: string | null;
};

export type ReviewBatchDecisionResult = {
  id: number;
  ok: boolean;
  review_status: "pending" | "approved" | "rejected" | null;
  idempotent: boolean;
  reviewed_at: string | null;
  review_note: string | null;
  error_code: "not_found" | "invalid_state" | null;
  error_detail: string | null;
};

export type ReviewBatchDecisionResponse = {
  decision: "approve" | "reject";
  total_requested: number;
  succeeded: number;
  failed: number;
  results: ReviewBatchDecisionResult[];
};

export type ReviewEditMode = "proposal" | "canonical";

export type ReviewEditEventPayload = {
  uid: string;
  title: string;
  course_label: string;
  start_at_utc: string;
  end_at_utc: string;
};

export type ReviewEditPreviewResponse = {
  mode: ReviewEditMode;
  event_uid: string;
  change_id: number | null;
  proposal_change_type: "created" | "due_changed" | null;
  base: ReviewEditEventPayload;
  candidate_after: ReviewEditEventPayload;
  delta_seconds: number | null;
  will_reject_pending_change_ids: number[];
  idempotent: boolean;
};

export type ReviewEditApplyResponse = {
  mode: ReviewEditMode;
  applied: boolean;
  idempotent: boolean;
  event_uid: string;
  edited_change_id: number | null;
  canonical_edit_change_id: number | null;
  rejected_pending_change_ids: number[];
  event: ReviewEditEventPayload;
};

export type LinkCandidate = {
  id: number;
  source_id: number;
  external_event_id: string;
  proposed_entity_uid: string | null;
  score: number | null;
  score_breakdown: Record<string, unknown>;
  reason_code: string;
  status: string;
  reviewed_by_user_id?: number | null;
  reviewed_at?: string | null;
  review_note?: string | null;
  created_at?: string;
  updated_at?: string;
  evidence_snapshot?: Record<string, unknown> | null;
  proposed_entity?: {
    entity_uid: string;
    course_best_display?: string | null;
    course_best_strength?: number | null;
  } | null;
};

export type LinkBlock = {
  id: number;
  source_id: number;
  external_event_id: string;
  blocked_entity_uid: string;
  note: string | null;
  created_at: string;
};

export type LinkRow = {
  id: number;
  source_id: number;
  source_kind: string;
  external_event_id: string;
  entity_uid: string;
  link_origin: string;
  link_score?: number | null;
  created_at?: string;
  updated_at?: string;
  signals?: Record<string, unknown> | null;
  linked_entity?: {
    entity_uid: string;
    course_best_display?: string | null;
    course_best_strength?: number | null;
  } | null;
};

export type LinkAlert = {
  id: number;
  source_id: number;
  external_event_id: string;
  entity_uid: string;
  link_id?: number | null;
  status: string;
  reason_code: string;
  resolution_code?: string | null;
  risk_level?: string | null;
  evidence_snapshot?: Record<string, unknown> | null;
  reviewed_at?: string | null;
  review_note?: string | null;
  linked_entity?: {
    entity_uid: string;
    course_best_display?: string | null;
    course_best_strength?: number | null;
  } | null;
};

export type UserProfile = {
  id: number;
  email: string | null;
  notify_email: string | null;
  timezone_name: string;
  calendar_delay_seconds: number;
  created_at?: string;
};
