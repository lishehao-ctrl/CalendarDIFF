export type AppConfig = {
  apiBase: string;
  apiKey: string;
};

export type SourceKindLiteral = "calendar" | "email" | "task" | "exam" | "announcement";
export type SourceProviderLiteral = "gmail" | "ics" | "calendar" | "outlook" | "canvas" | "moodle";

export type InputSource = {
  source_id: number;
  user_id: number;
  source_kind: SourceKindLiteral | string;
  provider: string;
  source_key: string;
  display_name: string | null;
  is_active: boolean;
  poll_interval_seconds: number;
  last_polled_at: string | null;
  next_poll_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  created_at: string;
  updated_at: string;
  config: Record<string, unknown>;
};

export type OAuthSessionCreateRequest = {
  source_id: number;
  provider: string;
};

export type OAuthSessionCreateResponse = {
  source_id: number;
  provider: string;
  authorization_url: string;
  expires_at: string;
};

export type SyncRequestCreateRequest = {
  source_id: number;
  trace_id?: string | null;
  metadata?: Record<string, unknown>;
};

export type SyncRequestCreateResponse = {
  request_id: string;
  source_id: number;
  trigger_type: "manual" | "scheduler" | "webhook";
  status: "PENDING" | "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  created_at: string;
  idempotency_key: string;
};

export type SyncRequestStatusResponse = {
  request_id: string;
  source_id: number;
  trigger_type: "manual" | "scheduler" | "webhook";
  status: "PENDING" | "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  idempotency_key: string;
  trace_id: string | null;
  error_code: string | null;
  error_message: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  connector_result:
    | {
        provider: string;
        status: string;
        fetched_at: string;
        error_code: string | null;
        error_message: string | null;
        records_count: number;
      }
    | null;
  applied: boolean;
  applied_at: string | null;
};

export type SourceSyncBusyDetail = {
  status?: "LOCK_SKIPPED";
  code: "source_sync_busy";
  message: string;
  retry_after_seconds: number;
  recoverable: boolean;
};

export type SourceInactiveDetail = {
  code: "source_inactive";
  message: string;
};

export type EventListItem = {
  id: number;
  source_id: number;
  uid: string;
  course_label: string;
  title: string;
  start_at_utc: string;
  end_at_utc: string;
  updated_at: string;
  source_label: string;
  source_kind: "calendar" | "email";
};

export type ChangeRecord = {
  id: number;
  source_id: number;
  event_uid: string;
  change_type: "created" | "removed" | "due_changed" | string;
  detected_at: string;
  before_json: Record<string, unknown> | null;
  after_json: Record<string, unknown> | null;
  delta_seconds: number | null;
  before_snapshot_id: number | null;
  after_snapshot_id: number;
  has_before_evidence: boolean;
  has_after_evidence: boolean;
  before_evidence_kind: string | null;
  after_evidence_kind: string | null;
  viewed_at: string | null;
  viewed_note: string | null;
};

export type EvidencePreviewEvent = {
  uid: string | null;
  summary: string | null;
  dtstart: string | null;
  dtend: string | null;
  location: string | null;
  description: string | null;
};

export type EvidencePreviewResponse = {
  side: "before" | "after";
  content_type: string;
  truncated: boolean;
  filename: string;
  event_count: number;
  events: EvidencePreviewEvent[];
  preview_text: string | null;
};

export type ChangeSummarySide = {
  value_time: string | null;
  source_label: string | null;
  source_kind: "calendar" | "email" | null;
  source_observed_at: string | null;
};

export type ChangeSummary = {
  old: ChangeSummarySide;
  new: ChangeSummarySide;
};

export type ChangeFeedRecord = ChangeRecord & {
  source_kind: "calendar" | "email" | string;
  priority_rank: number;
  priority_label: string;
  notification_state: string | null;
  deliver_after: string | null;
  change_summary?: ChangeSummary | null;
};

export type HealthResponse = {
  status: string;
  timestamp: string;
  db: {
    ok: boolean;
    error: string | null;
  };
  scheduler: {
    running: boolean;
    last_run_started_at: string | null;
    last_run_finished_at: string | null;
    last_error: string | null;
    last_skip_reason: string | null;
    last_synced_sources: number;
    last_run_success_count: number;
    last_run_failed_count: number;
    last_run_notification_failed_count: number;
    cumulative_success_count: number;
    cumulative_failed_count: number;
    cumulative_notification_failed_count: number;
    cumulative_run_executed_count: number;
    cumulative_run_skipped_lock_count: number;
    last_tick_at: string | null;
    last_tick_lock_acquired: boolean | null;
    instance_id: string | null;
    next_expected_check_at: string | null;
    next_expected_source_id: number | null;
    schema_guard_blocked: boolean;
    schema_guard_message: string | null;
    last_retention_cleanup_at: string | null;
  };
};

export type OnboardingStage = "needs_user" | "needs_source_connection" | "ready";

export type OnboardingStatus = {
  stage: OnboardingStage;
  message: string;
  registered_user_id: number | null;
  first_source_id: number | null;
  last_error: string | null;
};

export type OnboardingRegisterRequest = {
  notify_email: string;
};

export type OnboardingRegisterResponse = {
  status: "accepted";
  user_id: number;
  stage: "needs_source_connection" | "ready";
  first_source_id: number | null;
};

export type DashboardUser = {
  id: number;
  email: string | null;
  name?: string;
  notify_email: string | null;
  calendar_delay_seconds: number;
  created_at: string;
};

export type EmailRoute = "drop" | "archive" | "review";

export type EmailQueueActionItem = {
  action: string | null;
  due_iso: string | null;
  where: string | null;
};

export type EmailMatchedSnippet = {
  rule: string;
  snippet: string;
};

export type EmailQueueRuleAnalysis = {
  event_flags: Record<string, boolean>;
  matched_snippets: EmailMatchedSnippet[];
  drop_reason_codes: string[];
};

export type EmailQueueFlags = {
  viewed: boolean;
  notified: boolean;
  viewed_at: string | null;
  notified_at: string | null;
};

export type EmailQueueItem = {
  email_id: string;
  from_addr: string | null;
  subject: string | null;
  date_rfc822: string | null;
  route: EmailRoute;
  event_type: string | null;
  confidence: number;
  reasons: string[];
  course_hints: string[];
  action_items: EmailQueueActionItem[];
  rule_analysis: EmailQueueRuleAnalysis;
  flags: EmailQueueFlags;
};

export type UpdateEmailRouteRequest = {
  route: EmailRoute;
};

export type UpdateEmailRouteResponse = {
  email_id: string;
  route: EmailRoute;
  routed_at: string;
  notified_at: string | null;
};

export type MarkEmailViewedResponse = {
  email_id: string;
  viewed_at: string;
};
