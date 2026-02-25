export type AppConfig = {
  apiBase: string;
  apiKey: string;
  appEnv?: string;
  enableDevEndpoints?: boolean;
};

export type Input = {
  id: number;
  type: string;
  display_label: string;
  provider: string | null;
  gmail_label: string | null;
  gmail_from_contains: string | null;
  gmail_subject_keywords: string[] | null;
  gmail_account_email: string | null;
  notify_email: string | null;
  interval_minutes: number;
  is_active: boolean;
  last_checked_at: string | null;
  last_ok_at: string | null;
  last_change_detected_at: string | null;
  last_error_at: string | null;
  last_email_sent_at: string | null;
  next_check_at: string | null;
  last_result: string | null;
  last_error: string | null;
  created_at: string;
};

export type InputCreateResponse = Input & {
  upserted_existing: boolean;
};

export type GmailOAuthStartRequest = {
  label?: string | null;
  from_contains?: string | null;
  subject_keywords?: string[] | null;
};

export type GmailOAuthStartResponse = {
  authorization_url: string;
  expires_at: string;
};

export type ManualSyncResponse = {
  input_id: number;
  changes_created: number;
  email_sent: boolean;
  last_error: string | null;
  is_baseline_sync: boolean;
  notification_state: string | null;
};

export type SourceBusyDetail = {
  status?: "LOCK_SKIPPED";
  code: "input_busy";
  message: string;
  retry_after_seconds: number;
  recoverable: boolean;
};

export type DeadlineItem = {
  uid: string;
  title: string;
  ddl_type: string;
  start_at_utc: string;
  end_at_utc: string;
};

export type CourseDeadlines = {
  course_label: string;
  deadlines: DeadlineItem[];
};

export type InputDeadlines = {
  input_id: number;
  input_label: string | null;
  fetched_at_utc: string;
  total_deadlines: number;
  courses: CourseDeadlines[];
};

export type CourseOverride = {
  id: number;
  input_id: number;
  original_course_label: string;
  display_course_label: string;
  created_at: string;
  updated_at: string;
};

export type TaskOverride = {
  id: number;
  input_id: number;
  event_uid: string;
  display_title: string;
  created_at: string;
  updated_at: string;
};

export type InputOverrides = {
  input_id: number;
  courses: CourseOverride[];
  tasks: TaskOverride[];
};

export type ChangeRecord = {
  id: number;
  input_id: number;
  event_uid: string;
  change_type: string;
  detected_at: string;
  before_json: Record<string, unknown> | null;
  after_json: Record<string, unknown> | null;
  delta_seconds: number | null;
  before_snapshot_id: number | null;
  after_snapshot_id: number;
  evidence_keys: Record<string, unknown> | null;
  before_raw_evidence_key: Record<string, unknown> | null;
  after_raw_evidence_key: Record<string, unknown> | null;
  viewed_at: string | null;
  viewed_note: string | null;
};

export type EvidencePreviewResponse = {
  side: "before" | "after";
  content_type: string;
  truncated: boolean;
  filename: string;
  event_count: number;
  events: EvidencePreviewEvent[];
};

export type EvidencePreviewEvent = {
  uid: string | null;
  summary: string | null;
  dtstart: string | null;
  dtend: string | null;
  location: string | null;
  description: string | null;
};

export type ChangeSummarySide = {
  value_time: string | null;
  source_label: string | null;
  source_type: "ics" | "email" | null;
  source_observed_at: string | null;
};

export type ChangeSummary = {
  old: ChangeSummarySide;
  new: ChangeSummarySide;
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
    next_expected_input_id: number | null;
    schema_guard_blocked: boolean;
    schema_guard_message: string | null;
    last_retention_cleanup_at: string | null;
  };
};

export type StatusResponse = {
  scheduler_last_tick_at: string | null;
  scheduler_lock_acquired: boolean | null;
  due_inputs_count: number;
  checked_in_last_5m_count: number;
  failed_in_last_1h_count: number;
  pending_delayed_notifications_count: number;
  schema_guard_blocked: boolean;
  schema_guard_message: string | null;
};

export type InputRun = {
  id: number;
  input_id: number;
  trigger_type: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  changes_count: number;
  error_code: string | null;
  error_message: string | null;
  duration_ms: number | null;
  lock_owner: string | null;
};

export type DashboardUser = {
  id: number;
  email: string | null;
  name: string;
  notify_email: string | null;
  calendar_delay_seconds: number;
  created_at: string;
};

export type OnboardingStage = "needs_user" | "needs_ics" | "needs_baseline" | "ready";

export type OnboardingStatus = {
  stage: OnboardingStage;
  message: string;
  registered_user_id: number | null;
  first_input_id: number | null;
  last_error: string | null;
};

export type OnboardingRegisterRequest = {
  notify_email: string;
  ics: {
    url: string;
  };
};

export type OnboardingRegisterResponse = {
  status: "ready";
  user_id: number;
  input_id: number;
  is_baseline_sync: boolean;
  changes_created: number;
};

export type EmailRoute = "drop" | "archive" | "notify" | "review";

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

export type ApplyEmailReviewRequest = {
  mode?: "create_new" | "update_existing";
  target_input_id?: number;
  target_event_uid?: string;
  applied_due_at?: string | null;
  note?: string | null;
};

export type ApplyEmailReviewResponse = {
  task_id: number;
  change_id: number;
};

export type ChangeFeedRecord = ChangeRecord & {
  input_type: string;
  priority_rank: number;
  priority_label: string;
  notification_state: string | null;
  deliver_after: string | null;
  change_summary?: ChangeSummary | null;
};
