export type SourceHealth = {
  status: "healthy" | "attention" | "disconnected";
  message: string;
  affected_source_id: number | null;
  affected_provider: string | null;
};

export type OnboardingStage =
  | "needs_user"
  | "needs_canvas_ics"
  | "needs_gmail_or_skip"
  | "needs_monitoring_window"
  | "ready";

export type OnboardingMonitoringWindow = {
  monitor_since: string;
};

export type SyncProgress = {
  phase: string;
  label: string;
  detail?: string | null;
  current?: number | null;
  total?: number | null;
  percent?: number | null;
  unit?: string | null;
};

export type SourceOperatorGuidance = {
  recommended_action: "continue_review" | "continue_review_with_caution" | "wait_for_runtime" | "investigate_runtime";
  severity: "info" | "warning" | "blocking";
  reason_code: string;
  message: string;
  related_request_id?: string | null;
  progress_age_seconds?: number | null;
};

export type OnboardingSource = {
  source_id: number;
  provider: "ics" | "gmail";
  connected: boolean;
  has_monitoring_window: boolean;
  runtime_state: "active" | "inactive" | "archived" | "queued" | "running" | "rebind_pending";
  oauth_account_email?: string | null;
  monitoring_window: OnboardingMonitoringWindow | null;
};

export type OnboardingStatus = {
  stage: OnboardingStage;
  message: string;
  registered_user_id: number | null;
  first_source_id: number | null;
  source_health: SourceHealth | null;
  canvas_source: OnboardingSource | null;
  gmail_source: OnboardingSource | null;
  gmail_skipped: boolean;
  monitoring_window: OnboardingMonitoringWindow | null;
};

export type ChangesWorkbenchSourcesSummary = {
  active_count: number;
  running_count: number;
  queued_count: number;
  attention_count: number;
  blocking_count: number;
  recommended_action: "continue_review" | "continue_review_with_caution" | "wait_for_runtime" | "investigate_runtime";
  severity: "info" | "warning" | "blocking";
  reason_code: string;
  message: string;
  related_request_id?: string | null;
  progress_age_seconds?: number | null;
};

export type ChangesWorkbenchFamiliesSummary = {
  attention_count: number;
  pending_raw_type_suggestions: number;
  mappings_state: string;
  last_rebuilt_at: string | null;
  last_error: string | null;
};

export type ChangesWorkbenchManualSummary = {
  active_event_count: number;
  lane_role: "fallback";
};

export type WorkspacePosturePhase =
  | "baseline_import"
  | "initial_review"
  | "monitoring_live"
  | "attention_required";

export type WorkspacePostureInitialReview = {
  pending_count: number;
  reviewed_count: number;
  total_count: number;
  completion_percent: number;
  completed_at?: string | null;
};

export type WorkspacePostureMonitoring = {
  live_since?: string | null;
  replay_active: boolean;
  active_source_count: number;
};

export type WorkspacePostureNextAction = {
  lane: "sources" | "initial_review" | "changes" | "families" | "manual";
  label: string;
  reason: string;
};

export type WorkspacePosture = {
  phase: WorkspacePosturePhase;
  initial_review: WorkspacePostureInitialReview;
  monitoring: WorkspacePostureMonitoring;
  next_action: WorkspacePostureNextAction;
};

export type ChangesWorkbenchSummary = {
  changes_pending: number;
  baseline_review_pending: number;
  recommended_lane: "sources" | "initial_review" | "changes" | "families" | null;
  recommended_lane_reason_code: string;
  recommended_action_reason: string;
  workspace_posture: WorkspacePosture;
  sources: ChangesWorkbenchSourcesSummary;
  families: ChangesWorkbenchFamiliesSummary;
  manual: ChangesWorkbenchManualSummary;
  generated_at: string;
};

export type SourceProductPhase =
  | "importing_baseline"
  | "needs_initial_review"
  | "monitoring_live"
  | "needs_attention";

export type SourceRecoveryTrustState = "trusted" | "stale" | "partial" | "blocked";

export type SourceRecoveryAction = "reconnect_gmail" | "update_ics" | "retry_sync" | "wait";

export type SourceRecovery = {
  trust_state: SourceRecoveryTrustState;
  impact_summary: string;
  next_action: SourceRecoveryAction;
  next_action_label: string;
  last_good_sync_at?: string | null;
  degraded_since?: string | null;
  recovery_steps: string[];
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
  lifecycle_state?: "active" | "inactive" | "archived";
  sync_state?: "idle" | "queued" | "running";
  config_state?: "stable" | "rebind_pending";
  runtime_state?: "active" | "inactive" | "archived" | "queued" | "running" | "rebind_pending";
  active_request_id?: string | null;
  sync_progress?: SyncProgress | null;
  operator_guidance?: SourceOperatorGuidance | null;
  source_product_phase?: SourceProductPhase | null;
  source_recovery?: SourceRecovery | null;
};

export type SyncStatus = {
  request_id: string;
  source_id: number;
  trigger_type?: string;
  status: string;
  idempotency_key?: string | null;
  trace_id?: string | null;
  applied: boolean;
  created_at?: string;
  updated_at?: string;
  error_code: string | null;
  error_message: string | null;
  stage?: string | null;
  substage?: string | null;
  stage_updated_at?: string | null;
  connector_result: {
    status?: string;
    error_code?: string | null;
    error_message?: string | null;
  } | null;
  llm_usage?: Record<string, unknown> | null;
  metadata?: Record<string, unknown>;
  elapsed_ms?: number | null;
  applied_at?: string | null;
  progress?: SyncProgress | null;
};

export type SourceObservabilitySync = {
  request_id: string;
  phase: "bootstrap" | "replay";
  trigger_type: "manual" | "scheduler" | "webhook";
  status: "PENDING" | "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  created_at: string;
  updated_at: string;
  stage?: string | null;
  substage?: string | null;
  stage_updated_at?: string | null;
  applied: boolean;
  applied_at?: string | null;
  elapsed_ms?: number | null;
  error_code?: string | null;
  error_message?: string | null;
  connector_result?: Record<string, unknown> | null;
  llm_usage?: Record<string, unknown> | null;
  progress?: SyncProgress | null;
};

export type SourceBootstrapSummary = {
  imported_count: number;
  review_required_count: number;
  ignored_count: number;
  conflict_count: number;
  state: "idle" | "running" | "review_required" | "completed";
};

export type SourceObservabilityResponse = {
  source_id: number;
  active_request_id?: string | null;
  bootstrap: SourceObservabilitySync | null;
  bootstrap_summary?: SourceBootstrapSummary | null;
  latest_replay: SourceObservabilitySync | null;
  active: SourceObservabilitySync | null;
  operator_guidance?: SourceOperatorGuidance | null;
  source_product_phase?: SourceProductPhase | null;
  source_recovery?: SourceRecovery | null;
};

export type SourceSyncHistoryResponse = {
  source_id: number;
  items: SourceObservabilitySync[];
};

export type SyncUsageSummary = {
  successful_call_count: number;
  usage_record_count: number;
  latency_ms_total: number;
  latency_ms_max: number;
  input_tokens: number;
  cached_input_tokens: number;
  cache_creation_input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  total_tokens: number;
  cache_hit_ratio: number | null;
  avg_latency_ms: number | null;
  protocols: Record<string, number>;
  models: Record<string, number>;
  task_counts: Record<string, number>;
  last_observed_at?: string | null;
};

export type SourceObservabilityView = {
  source_id: number;
  source_label: string;
  source_kind: "calendar" | "email";
  runtime_state: string;
  connection_status: "healthy" | "attention" | "disconnected";
  connection_label: string;
  connection_detail: string;
  bootstrap_status: "idle" | "running" | "succeeded" | "failed" | "unknown";
  replay_status: "idle" | "running" | "succeeded" | "failed" | "unknown";
  latest_bootstrap_elapsed_ms: number | null;
  latest_replay_elapsed_ms: number | null;
  bootstrap_usage: SyncUsageSummary | null;
  replay_usage: SyncUsageSummary | null;
  latest_sync_label: string | null;
  latest_sync_detail: string | null;
};

export type IntakePostureView = {
  warming_source_count: number;
  replay_health: "healthy" | "attention" | "unknown";
  bootstrap_cost_state: "normal" | "elevated" | "unknown";
  replay_cost_state: "normal" | "elevated" | "unknown";
  warming_label: string;
  replay_label: string;
  cost_label: string;
};

export type EventDisplay = {
  course_display: string;
  family_name: string;
  ordinal: number | null;
  display_label: string;
};

export type UserFacingEvent = {
  uid?: string | null;
  event_display: EventDisplay;
  due_date?: string | null;
  due_time?: string | null;
  time_precision: "date_only" | "datetime" | string;
};

export type ChangeDecisionSupportAction =
  | "approve"
  | "reject"
  | "edit"
  | "review_carefully";

export type ChangeDecisionSupportRiskLevel = "low" | "medium" | "high";

export type ChangeDecisionOutcomePreview = {
  approve: string;
  reject: string;
  edit: string;
};

export type ChangeDecisionSupport = {
  why_now: string;
  suggested_action: ChangeDecisionSupportAction;
  suggested_action_reason: string;
  risk_level: ChangeDecisionSupportRiskLevel;
  risk_summary: string;
  key_facts: string[];
  outcome_preview: ChangeDecisionOutcomePreview;
};

export type ChangeItem = {
  id: number;
  entity_uid: string;
  change_type: string;
  change_origin: string;
  intake_phase: "baseline" | "replay";
  review_bucket: "initial_review" | "changes";
  detected_at: string;
  review_status: string;
  before_display: EventDisplay | null;
  after_display: EventDisplay | null;
  before_event: UserFacingEvent | null;
  after_event: UserFacingEvent | null;
  primary_source?: {
    source_id: number;
    source_kind?: string | null;
    provider?: string | null;
    external_event_id?: string | null;
  } | null;
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
  evidence_availability?: {
    before: boolean;
    after: boolean;
  };
  decision_support?: ChangeDecisionSupport | null;
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
  event_display?: EventDisplay | null;
  source_title?: string | null;
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

export type ChangeBatchDecisionResult = {
  id: number;
  ok: boolean;
  review_status: "pending" | "approved" | "rejected" | null;
  idempotent: boolean;
  reviewed_at: string | null;
  review_note: string | null;
  error_code: "not_found" | "invalid_state" | null;
  error_detail: string | null;
};

export type ChangeBatchDecisionResponse = {
  decision: "approve" | "reject";
  total_requested: number;
  succeeded: number;
  failed: number;
  results: ChangeBatchDecisionResult[];
};

export type ChangeEditMode = "proposal" | "canonical";

export type ChangeEditEventPayload = UserFacingEvent;

export type ChangeEditTarget = {
  change_id?: number;
  entity_uid?: string | null;
};

export type ChangeEditPatch = {
  event_name?: string | null;
  due_date?: string | null;
  due_time?: string | null;
  time_precision?: "date_only" | "datetime" | null;
  course_dept?: string | null;
  course_number?: number | null;
  course_suffix?: string | null;
  course_quarter?: "WI" | "SP" | "SU" | "FA" | null;
  course_year2?: number | null;
};

export type ChangeEditRequest = {
  mode: ChangeEditMode;
  target: ChangeEditTarget;
  patch: ChangeEditPatch;
  reason?: string | null;
};

export type ChangeEditContext = {
  change_id: number;
  entity_uid: string;
  editable_event: {
    uid: string;
    family_id?: number | null;
    family_name?: string | null;
    course_dept?: string | null;
    course_number?: number | null;
    course_suffix?: string | null;
    course_quarter?: "WI" | "SP" | "SU" | "FA" | null;
    course_year2?: number | null;
    raw_type?: string | null;
    event_name?: string | null;
    ordinal?: number | null;
    due_date?: string | null;
    due_time?: string | null;
    time_precision: "date_only" | "datetime";
  };
};

export type ChangeEditPreviewResponse = {
  mode: ChangeEditMode;
  entity_uid: string;
  change_id: number | null;
  proposal_change_type: "created" | "due_changed" | null;
  base: ChangeEditEventPayload;
  candidate_after: ChangeEditEventPayload;
  delta_seconds: number | null;
  will_reject_pending_change_ids: number[];
  idempotent: boolean;
};

export type ChangeEditApplyResponse = {
  mode: ChangeEditMode;
  applied: boolean;
  idempotent: boolean;
  entity_uid: string;
  edited_change_id: number | null;
  canonical_edit_change_id: number | null;
  rejected_pending_change_ids: number[];
  event: ChangeEditEventPayload;
};

export type CourseIdentity = {
  course_display: string;
  course_dept: string;
  course_number: number;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
};

export type CourseWorkItemFamily = {
  course_display: string;
  course_dept: string;
  course_number: number;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
  id: number;
  canonical_label: string;
  raw_types: string[];
  created_at: string;
  updated_at: string;
};

export type CourseWorkItemFamilyStatus = {
  state: string;
  last_rebuilt_at: string | null;
  last_error: string | null;
};

export type CourseWorkItemRawType = {
  course_display: string;
  course_dept: string;
  course_number: number;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
  id: number;
  family_id: number;
  raw_type: string;
  created_at: string;
  updated_at: string;
};

export type CourseWorkItemRawTypeMoveResponse = {
  course_display: string;
  course_dept: string;
  course_number: number;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
  raw_type_id: number;
  family_id: number;
  previous_family_id: number;
};

export type RawTypeSuggestionItem = {
  id: number;
  course_display: string;
  course_dept: string;
  course_number: number;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
  status: "pending" | "approved" | "rejected" | "dismissed";
  confidence: number;
  evidence?: string | null;
  source_observation_id?: number | null;
  source_raw_type?: string | null;
  source_raw_type_id?: number | null;
  source_family_id?: number | null;
  source_family_name?: string | null;
  suggested_raw_type?: string | null;
  suggested_raw_type_id?: number | null;
  suggested_family_id?: number | null;
  suggested_family_name?: string | null;
  review_note?: string | null;
  reviewed_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type RawTypeSuggestionDecisionResponse = {
  id: number;
  status: "pending" | "approved" | "rejected" | "dismissed";
  review_note?: string | null;
  reviewed_at?: string | null;
};

export type ManualEvent = {
  entity_uid: string;
  lifecycle: "active" | "removed";
  manual_support: boolean;
  family_id: number | null;
  family_name: string;
  course_display: string;
  course_dept: string;
  course_number: number;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
  raw_type?: string | null;
  event_name?: string | null;
  ordinal?: number | null;
  due_date?: string | null;
  due_time?: string | null;
  time_precision: "date_only" | "datetime" | string;
  event: UserFacingEvent | null;
  created_at: string;
  updated_at: string;
};

export type ManualEventMutationResponse = {
  applied: boolean;
  idempotent: boolean;
  change_id: number | null;
  entity_uid: string;
  lifecycle: "active" | "removed";
  event: ManualEvent | null;
};

export type UserProfile = {
  id: number;
  email: string;
  language_code: "en" | "zh-CN";
  timezone_name: string;
  timezone_source: "auto" | "manual";
  calendar_delay_seconds: number;
  created_at?: string;
};

export type McpAccessToken = {
  token_id: string;
  label: string;
  scopes: string[];
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
};

export type McpAccessTokenCreateResponse = McpAccessToken & {
  token: string;
};

export type AgentRiskLevel = "low" | "medium" | "high";
export type AgentConditionSeverity = "info" | "warning" | "blocking";
export type AgentProposalType =
  | "change_decision"
  | "source_recovery"
  | "family_relink_preview"
  | "label_learning_commit"
  | "proposal_edit_commit";
export type AgentProposalStatus = "open" | "accepted" | "rejected" | "expired" | "superseded";
export type ApprovalTicketStatus = "open" | "executed" | "canceled" | "expired" | "failed";

export type AgentBlockingCondition = {
  code: string;
  message: string;
  severity: AgentConditionSeverity;
};

export type AgentRecommendedAction = {
  lane: "sources" | "initial_review" | "changes" | "families" | "manual";
  label: string;
  reason: string;
  reason_code: string;
  reason_params: Record<string, unknown>;
  risk_level: AgentRiskLevel;
  recommended_tool: string;
};

export type AgentWorkspaceContext = {
  generated_at: string;
  summary: ChangesWorkbenchSummary;
  top_pending_changes: ChangeItem[];
  recommended_next_action: AgentRecommendedAction;
  blocking_conditions: AgentBlockingCondition[];
  available_next_tools: string[];
};

export type AgentChangeContext = {
  generated_at: string;
  change: ChangeItem;
  recommended_next_action: AgentRecommendedAction;
  blocking_conditions: AgentBlockingCondition[];
  available_next_tools: string[];
};

export type AgentSourceContextSource = SourceRow & {
  user_id: number;
};

export type AgentSourceContext = {
  generated_at: string;
  source: AgentSourceContextSource;
  observability: SourceObservabilityResponse;
  active_sync_request: SyncStatus | null;
  recommended_next_action: AgentRecommendedAction;
  blocking_conditions: AgentBlockingCondition[];
  available_next_tools: string[];
};

export type AgentFamilyContext = {
  generated_at: string;
  family: CourseWorkItemFamily;
  raw_types: CourseWorkItemRawType[];
  pending_raw_type_suggestions: RawTypeSuggestionItem[];
  recommended_next_action: AgentRecommendedAction;
  blocking_conditions: AgentBlockingCondition[];
  available_next_tools: string[];
};

export type AgentProposal = {
  proposal_id: number;
  owner_user_id: number;
  proposal_type: AgentProposalType;
  status: AgentProposalStatus;
  target_kind: string;
  target_id: string;
  summary: string;
  summary_code: string;
  reason: string;
  reason_code: string;
  risk_level: AgentRiskLevel;
  confidence: number;
  suggested_action: string;
  origin_kind: string;
  origin_label: string;
  origin_request_id: string | null;
  lifecycle_code: string;
  execution_mode: "approval_ticket_required" | "web_only";
  execution_mode_code: string;
  next_step_code: string;
  can_create_ticket: boolean;
  suggested_payload: Record<string, unknown>;
  context: Record<string, unknown>;
  target_snapshot: Record<string, unknown>;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ApprovalTicket = {
  ticket_id: string;
  proposal_id: number;
  owner_user_id: number;
  channel: string;
  action_type: string;
  target_kind: string;
  target_id: string;
  payload: Record<string, unknown>;
  payload_hash: string;
  target_snapshot: Record<string, unknown>;
  risk_level: AgentRiskLevel;
  origin_kind: string;
  origin_label: string;
  origin_request_id: string | null;
  status: ApprovalTicketStatus;
  lifecycle_code: string;
  next_step_code: string;
  confirm_summary_code: string;
  cancel_summary_code: string;
  transition_message_code: string;
  social_safe_cta_code: string | null;
  can_confirm: boolean;
  can_cancel: boolean;
  last_transition_kind: string;
  last_transition_label: string;
  executed_result: Record<string, unknown>;
  expires_at: string | null;
  confirmed_at: string | null;
  canceled_at: string | null;
  executed_at: string | null;
  created_at: string;
  updated_at: string;
};


export type LabelLearningFamilyOption = {
  id: number;
  course_display: string;
  course_dept: string;
  course_number: number;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
  canonical_label: string;
  raw_types: string[];
};

export type LabelLearningPreview = {
  change_id: number;
  course_display: string | null;
  course_dept?: string | null;
  course_number?: number | null;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
  raw_label: string | null;
  ordinal: number | null;
  status: "resolved" | "unresolved";
  resolved_family_id?: number | null;
  resolved_canonical_label?: string | null;
  families: LabelLearningFamilyOption[];
};

export type LabelLearningApplyResponse = {
  applied: boolean;
  course_display: string | null;
  course_dept?: string | null;
  course_number?: number | null;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
  raw_label: string | null;
  family_id: number | null;
  canonical_label: string | null;
  approved_change_id: number | null;
};
