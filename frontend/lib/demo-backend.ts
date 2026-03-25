"use client";

import type {
  AgentBlockingCondition,
  AgentChangeContext,
  AgentProposal,
  AgentRecommendedAction,
  AgentSourceContext,
  AgentWorkspaceContext,
  ApprovalTicket,
  ChangesWorkbenchSummary,
  ChangeDecisionSupport,
  CourseIdentity,
  CourseWorkItemFamily,
  CourseWorkItemFamilyStatus,
  CourseWorkItemRawType,
  EvidencePreviewResponse,
  LabelLearningApplyResponse,
  LabelLearningPreview,
  McpAccessToken,
  McpAccessTokenCreateResponse,
  ManualEvent,
  ManualEventMutationResponse,
  OnboardingStatus,
  RawTypeSuggestionDecisionResponse,
  RawTypeSuggestionItem,
  ChangeBatchDecisionResponse,
  ChangeItem,
  ChangeEditApplyResponse,
  ChangeEditContext,
  ChangeEditPreviewResponse,
  ChangeEditRequest,
  SourceRow,
  SourceObservabilityResponse,
  SourceObservabilitySync,
  SourceSyncHistoryResponse,
  SyncStatus,
  UserProfile,
} from "@/lib/types";

type DemoState = {
  user: UserProfile;
  onboarding: OnboardingStatus;
  sources: SourceRow[];
  changes: ChangeItem[];
  evidence: Record<string, EvidencePreviewResponse>;
  families: CourseWorkItemFamily[];
  rawTypes: CourseWorkItemRawType[];
  rawTypeSuggestions: RawTypeSuggestionItem[];
  familyStatus: CourseWorkItemFamilyStatus;
  manualEvents: ManualEvent[];
  mcpTokens: McpAccessToken[];
  agentProposals: AgentProposal[];
  approvalTickets: ApprovalTicket[];
};

const nowIso = "2026-03-18T05:20:00.000Z";

let demoState: DemoState = createInitialDemoState();

function createInitialDemoState(): DemoState {
  const families: CourseWorkItemFamily[] = [
    familyRow(11, "CSE", 120, null, "WI", 26, "Homework", ["hw", "homework", "problem set"]),
    familyRow(12, "CSE", 120, null, "WI", 26, "Quiz", ["quiz", "check-in", "weekly quiz"]),
    familyRow(13, "CSE", 151, "A", "WI", 26, "Project", ["project milestone", "milestone", "checkpoint"]),
    familyRow(14, "MATH", 18, null, "WI", 26, "Worksheet", ["worksheet", "practice set"]),
    familyRow(15, "CHEM", 6, "A", "WI", 26, "Lab Report", ["lab report", "write-up"]),
  ];

  const changes: ChangeItem[] = [
    changeRow({
      id: 401,
      courseDisplay: "CSE 120 WI26",
      familyName: "Homework",
      label: "Homework 4",
      changeType: "updated",
      beforeDate: "2026-03-20",
      beforeTime: "23:59:00",
      afterDate: "2026-03-22",
      afterTime: "23:59:00",
      primarySource: { source_id: 2, source_kind: "email", provider: "gmail", external_event_id: "msg-hw4" },
      proposalSources: [
        { source_id: 2, source_kind: "email", provider: "gmail", external_event_id: "msg-hw4", confidence: 0.96 },
        { source_id: 1, source_kind: "calendar", provider: "ics", external_event_id: "evt-hw4", confidence: 0.82 },
      ],
      priorityLabel: "high attention",
      reviewStatus: "pending",
      sourceLabelOld: "Canvas assignment",
      sourceLabelNew: "Professor announcement",
      intakePhase: "replay",
      reviewBucket: "changes",
    }),
    changeRow({
      id: 402,
      courseDisplay: "CSE 151A WI26",
      familyName: "Project",
      label: "Project Milestone 2",
      changeType: "updated",
      beforeDate: "2026-03-19",
      beforeTime: "17:00:00",
      afterDate: "2026-03-21",
      afterTime: "17:00:00",
      primarySource: { source_id: 2, source_kind: "email", provider: "gmail", external_event_id: "msg-proj2" },
      proposalSources: [{ source_id: 2, source_kind: "email", provider: "gmail", external_event_id: "msg-proj2", confidence: 0.93 }],
      priorityLabel: "normal",
      reviewStatus: "pending",
      sourceLabelOld: "Canvas due card",
      sourceLabelNew: "Staff alias bulletin",
      intakePhase: "replay",
      reviewBucket: "changes",
    }),
    changeRow({
      id: 403,
      courseDisplay: "MATH 18 WI26",
      familyName: "Worksheet",
      label: "Worksheet 7",
      changeType: "created",
      beforeDate: null,
      beforeTime: null,
      afterDate: "2026-03-25",
      afterTime: "23:00:00",
      primarySource: { source_id: 1, source_kind: "calendar", provider: "ics", external_event_id: "evt-ws7" },
      proposalSources: [{ source_id: 1, source_kind: "calendar", provider: "ics", external_event_id: "evt-ws7", confidence: 0.88 }],
      priorityLabel: "new work",
      reviewStatus: "pending",
      sourceLabelOld: null,
      sourceLabelNew: "Canvas calendar",
      intakePhase: "baseline",
      reviewBucket: "initial_review",
    }),
    changeRow({
      id: 404,
      courseDisplay: "CHEM 6A WI26",
      familyName: "Lab Report",
      label: "Lab Report 2",
      changeType: "updated",
      beforeDate: "2026-03-18",
      beforeTime: "23:59:00",
      afterDate: "2026-03-20",
      afterTime: "23:59:00",
      primarySource: { source_id: 2, source_kind: "email", provider: "gmail", external_event_id: "msg-lr2" },
      proposalSources: [{ source_id: 2, source_kind: "email", provider: "gmail", external_event_id: "msg-lr2", confidence: 0.9 }],
      priorityLabel: "needs review",
      reviewStatus: "approved",
      sourceLabelOld: "Lab rubric post",
      sourceLabelNew: "TA follow-up",
      intakePhase: "replay",
      reviewBucket: "changes",
    }),
    changeRow({
      id: 405,
      courseDisplay: "CSE 120 WI26",
      familyName: "Quiz",
      label: "Quiz 1",
      changeType: "created",
      beforeDate: null,
      beforeTime: null,
      afterDate: "2026-03-12",
      afterTime: "18:00:00",
      primarySource: { source_id: 1, source_kind: "calendar", provider: "ics", external_event_id: "evt-quiz-1" },
      proposalSources: [{ source_id: 1, source_kind: "calendar", provider: "ics", external_event_id: "evt-quiz-1", confidence: 0.84 }],
      priorityLabel: "baseline ready",
      reviewStatus: "approved",
      sourceLabelOld: null,
      sourceLabelNew: "Canvas quiz post",
      intakePhase: "baseline",
      reviewBucket: "initial_review",
    }),
  ];

  return {
    user: {
      id: 9001,
      email: "demo@calendardiff.app",
      language_code: "en" as const,
      timezone_name: "America/Los_Angeles",
      timezone_source: "manual",
      calendar_delay_seconds: 120,
      created_at: "2026-03-10T18:00:00.000Z",
    },
    onboarding: {
      stage: "ready",
      message: "Preview mode is showing a realistic workspace snapshot with mixed source health and pending review work.",
      registered_user_id: 9001,
      first_source_id: 1,
      source_health: {
        status: "attention",
        message: "A connected source needs attention before syncs are fully reliable.",
        affected_source_id: 2,
        affected_provider: "gmail",
      },
      canvas_source: {
        source_id: 1,
        provider: "ics",
        connected: true,
        has_monitoring_window: true,
        runtime_state: "active",
        monitoring_window: {
          monitor_since: "2025-12-12",
        },
      },
      gmail_source: {
        source_id: 2,
        provider: "gmail",
        connected: true,
        has_monitoring_window: true,
        runtime_state: "active",
        oauth_account_email: "demo-inbox@school.edu",
        monitoring_window: {
          monitor_since: "2025-12-12",
        },
      },
      gmail_skipped: false,
      monitoring_window: {
        monitor_since: "2025-12-12",
      },
    },
    sources: [
      {
        source_id: 1,
        source_kind: "calendar",
        provider: "ics",
        source_key: "canvas_ics_demo",
        display_name: "Canvas ICS",
        is_active: true,
        poll_interval_seconds: 900,
        last_polled_at: "2026-03-18T05:05:00.000Z",
        next_poll_at: "2026-03-18T05:20:00.000Z",
        last_error_code: null,
        last_error_message: null,
        config: {},
        lifecycle_state: "active",
        sync_state: "idle",
        config_state: "stable",
        runtime_state: "active",
        source_product_phase: "needs_initial_review",
        source_recovery: {
          trust_state: "partial",
          impact_summary: "Imported baseline items are visible, but one item still needs Initial Review before this source is fully trusted for monitoring.",
          next_action: "wait",
          next_action_label: "Finish Initial Review",
          last_good_sync_at: "2026-03-18T05:05:00.000Z",
          degraded_since: "2026-03-18T05:05:00.000Z",
          recovery_steps: [
            "Review the remaining baseline item.",
            "Approve or reject it before relying on day-to-day replay.",
          ],
        },
      },
      {
        source_id: 2,
        source_kind: "email",
        provider: "gmail",
        source_key: "gmail_inbox_demo",
        display_name: "Gmail Inbox",
        is_active: true,
        poll_interval_seconds: 900,
        last_polled_at: "2026-03-18T05:04:00.000Z",
        next_poll_at: "2026-03-18T05:19:00.000Z",
        last_error_code: "oauth_expired",
        last_error_message: "Google credentials expired. This is intentional in preview mode so the Sources lane shows an attention state.",
        config: {},
        oauth_connection_status: "connected",
        oauth_account_email: "demo-inbox@school.edu",
        lifecycle_state: "active",
        sync_state: "idle",
        config_state: "stable",
        runtime_state: "active",
        operator_guidance: {
          recommended_action: "investigate_runtime",
          severity: "warning",
          reason_code: "oauth_expired",
          message: "Reconnect Gmail before trusting replay.",
          related_request_id: null,
          progress_age_seconds: null,
        },
        source_product_phase: "needs_attention",
        source_recovery: {
          trust_state: "blocked",
          impact_summary: "New Gmail-based changes may be missing until the mailbox is reconnected.",
          next_action: "reconnect_gmail",
          next_action_label: "Reconnect Gmail",
          last_good_sync_at: "2026-03-17T04:40:00.000Z",
          degraded_since: "2026-03-18T04:58:00.000Z",
          recovery_steps: [
            "Reconnect the Gmail mailbox.",
            "Run a sync to verify replay resumes.",
          ],
        },
      },
    ],
    changes,
    evidence: buildEvidence(changes),
    families,
    rawTypes: [
      rawTypeRow(201, families[0], "hw"),
      rawTypeRow(202, families[0], "homework"),
      rawTypeRow(203, families[0], "problem set"),
      rawTypeRow(204, families[1], "quiz"),
      rawTypeRow(205, families[1], "check-in"),
      rawTypeRow(206, families[1], "weekly quiz"),
      rawTypeRow(207, families[2], "project milestone"),
      rawTypeRow(208, families[2], "milestone"),
      rawTypeRow(209, families[2], "checkpoint"),
      rawTypeRow(210, families[3], "worksheet"),
      rawTypeRow(211, families[3], "practice set"),
      rawTypeRow(212, families[4], "lab report"),
      rawTypeRow(213, families[4], "write-up"),
    ],
    rawTypeSuggestions: [
      rawTypeSuggestionRow(301, families[1], "weekly quiz", families[0], "homework", 0.78, "Some instructors still call this work 'weekly quiz', but the deadline pattern overlaps with homework posts."),
      rawTypeSuggestionRow(302, families[2], "checkpoint", families[1], "quiz", 0.67, "Checkpoint notices and quiz reminders share the same short-form naming in this course."),
      rawTypeSuggestionRow(303, families[4], "write-up", families[0], "problem set", 0.72, "Write-up and problem set language are drifting together in recent course announcements."),
      rawTypeSuggestionRow(304, families[3], "practice set", families[0], "homework", 0.82, "Practice set is increasingly being used as the homework label in MATH 18."),
    ],
    familyStatus: {
      state: "idle",
      last_rebuilt_at: "2026-03-18T04:58:00.000Z",
      last_error: null,
    },
    manualEvents: [
      manualRow("man-1", families[0], "Homework 1", 1, "2026-03-15", "23:59:00"),
      manualRow("man-2", families[2], "Project Milestone 1", 1, "2026-03-12", "17:00:00"),
      manualRow("man-3", families[4], "Lab Report 1", 1, "2026-03-14", "23:59:00"),
    ],
    mcpTokens: [
      {
        token_id: "mcp_tok_active_1",
        label: "OpenClaw laptop",
        scopes: ["calendar.read", "changes.write"],
        last_used_at: "2026-03-17T21:35:00.000Z",
        expires_at: "2026-06-16T00:00:00.000Z",
        revoked_at: null,
        created_at: "2026-03-10T08:00:00.000Z",
      },
      {
        token_id: "mcp_tok_revoked_1",
        label: "OpenClaw desktop",
        scopes: ["calendar.read"],
        last_used_at: "2026-03-12T19:00:00.000Z",
        expires_at: "2026-04-15T00:00:00.000Z",
        revoked_at: "2026-03-16T02:10:00.000Z",
        created_at: "2026-03-11T09:30:00.000Z",
      },
    ],
    agentProposals: [],
    approvalTickets: [],
  };
}

function familyRow(
  id: number,
  dept: string,
  number: number,
  suffix: string | null,
  quarter: string | null,
  year2: number | null,
  canonical_label: string,
  raw_types: string[],
): CourseWorkItemFamily {
  const course_display = `${dept} ${number}${suffix || ""}${quarter ? ` ${quarter}${String(year2).padStart(2, "0")}` : ""}`.trim();
  return {
    id,
    course_display,
    course_dept: dept,
    course_number: number,
    course_suffix: suffix,
    course_quarter: quarter,
    course_year2: year2,
    canonical_label,
    raw_types,
    created_at: nowIso,
    updated_at: nowIso,
  };
}

function rawTypeRow(id: number, family: CourseWorkItemFamily, rawType: string): CourseWorkItemRawType {
  return {
    id,
    family_id: family.id,
    raw_type: rawType,
    course_display: family.course_display,
    course_dept: family.course_dept,
    course_number: family.course_number,
    course_suffix: family.course_suffix,
    course_quarter: family.course_quarter,
    course_year2: family.course_year2,
    created_at: nowIso,
    updated_at: nowIso,
  };
}

function rawTypeSuggestionRow(
  id: number,
  sourceFamily: CourseWorkItemFamily,
  sourceRawType: string,
  suggestedFamily: CourseWorkItemFamily,
  suggestedRawType: string,
  confidence: number,
  evidence: string,
): RawTypeSuggestionItem {
  const sourceRawTypeId = 1000 + id * 2;
  const suggestedRawTypeId = 1000 + id * 2 + 1;
  return {
    id,
    course_display: sourceFamily.course_display,
    course_dept: sourceFamily.course_dept,
    course_number: sourceFamily.course_number,
    course_suffix: sourceFamily.course_suffix,
    course_quarter: sourceFamily.course_quarter,
    course_year2: sourceFamily.course_year2,
    status: "pending",
    confidence,
    evidence,
    source_observation_id: 8000 + id,
    source_raw_type: sourceRawType,
    source_raw_type_id: sourceRawTypeId,
    source_family_id: sourceFamily.id,
    source_family_name: sourceFamily.canonical_label,
    suggested_raw_type: suggestedRawType,
    suggested_raw_type_id: suggestedRawTypeId,
    suggested_family_id: suggestedFamily.id,
    suggested_family_name: suggestedFamily.canonical_label,
    review_note: null,
    reviewed_at: null,
    created_at: nowIso,
    updated_at: nowIso,
  };
}

function eventDisplay(courseDisplay: string, familyName: string, ordinal: number | null, label: string) {
  return {
    course_display: courseDisplay,
    family_name: familyName,
    ordinal,
    display_label: label,
  };
}

function userFacingEvent(courseDisplay: string, familyName: string, label: string, ordinal: number | null, dueDate: string | null, dueTime: string | null) {
  return {
    uid: `${courseDisplay}-${familyName}-${ordinal || "x"}`,
    event_display: eventDisplay(courseDisplay, familyName, ordinal, label),
    due_date: dueDate,
    due_time: dueTime,
    time_precision: dueTime ? "datetime" : "date_only",
  };
}

function buildDecisionSupport(input: {
  changeType: string;
  intakePhase: ChangeItem["intake_phase"];
  primarySource: ChangeItem["primary_source"];
  label: string;
  beforeDate: string | null;
  afterDate: string | null;
}): ChangeDecisionSupport {
  if (input.intakePhase === "baseline") {
    return {
      why_now: "This item came from the first baseline import and still needs an initial decision before monitoring can fully settle.",
      suggested_action: "approve",
      suggested_action_reason: "The source provided a concrete initial deadline, so approving will establish the starting live state.",
      risk_level: "medium",
      risk_summary: "If this baseline item is wrong, the first live version of the event will start from the wrong date.",
      key_facts: [
        `${input.label} is part of the initial import`,
        input.primarySource?.provider === "ics" ? "Observed on the calendar feed" : "Observed from mailbox evidence",
        input.afterDate ? `New date ${input.afterDate}` : "No existing live date yet",
      ],
      outcome_preview: {
        approve: "Create the initial live version",
        reject: "Keep this baseline item out of the live state",
        edit: "Correct the imported details before creating the live version",
      },
    };
  }

  return {
    why_now: "A connected source observed a live change after the baseline was established, so replay review is required before the live state updates.",
    suggested_action: input.changeType === "updated" ? "approve" : input.changeType === "created" ? "review_carefully" : "review_carefully",
    suggested_action_reason:
      input.changeType === "updated"
        ? "The new source evidence points to a concrete time change."
        : "The system found a new item, but you should confirm it belongs in the live schedule.",
    risk_level: input.changeType === "updated" ? "medium" : "high",
    risk_summary:
      input.changeType === "updated"
        ? "Approving updates the live deadline immediately. Rejecting keeps the current live version."
        : "Approving may add a new live deadline. Rejecting leaves the current schedule unchanged.",
    key_facts: [
      input.beforeDate ? `Previous date ${input.beforeDate}` : "No previous live date",
      input.afterDate ? `Observed date ${input.afterDate}` : "No observed replacement date",
      input.primarySource?.provider === "gmail" ? "Mailbox evidence is attached" : "Calendar evidence is attached",
    ],
    outcome_preview: {
      approve: "Update live deadline",
      reject: "Keep current version",
      edit: "Correct details before updating live state",
    },
  };
}

function changeRow(input: {
  id: number;
  courseDisplay: string;
  familyName: string;
  label: string;
  changeType: string;
  beforeDate: string | null;
  beforeTime: string | null;
  afterDate: string | null;
  afterTime: string | null;
  primarySource: ChangeItem["primary_source"];
  proposalSources: ChangeItem["proposal_sources"];
  priorityLabel: string;
  reviewStatus: string;
  sourceLabelOld: string | null;
  sourceLabelNew: string | null;
  intakePhase?: ChangeItem["intake_phase"];
  reviewBucket?: ChangeItem["review_bucket"];
}) : ChangeItem {
  const ordinal = Number((input.label.match(/(\d+)/)?.[1] || "0")) || null;
  return {
    id: input.id,
    entity_uid: `demo-change-${input.id}`,
    change_type: input.changeType,
    change_origin: "ingest_proposal",
    intake_phase: input.intakePhase || "replay",
    review_bucket: input.reviewBucket || "changes",
    detected_at: "2026-03-18T04:40:00.000Z",
    review_status: input.reviewStatus,
    before_display: input.beforeDate ? eventDisplay(input.courseDisplay, input.familyName, ordinal, input.label) : null,
    after_display: input.afterDate ? eventDisplay(input.courseDisplay, input.familyName, ordinal, input.label) : null,
    before_event: input.beforeDate ? userFacingEvent(input.courseDisplay, input.familyName, input.label, ordinal, input.beforeDate, input.beforeTime) : null,
    after_event: input.afterDate ? userFacingEvent(input.courseDisplay, input.familyName, input.label, ordinal, input.afterDate, input.afterTime) : null,
    primary_source: input.primarySource,
    proposal_sources: input.proposalSources,
    viewed_at: input.reviewStatus === "pending" ? null : "2026-03-18T04:48:00.000Z",
    viewed_note: null,
    reviewed_at: input.reviewStatus === "pending" ? null : "2026-03-18T04:52:00.000Z",
    review_note: input.reviewStatus === "pending" ? null : "Preview mode auto-note",
    priority_rank: input.reviewStatus === "pending" ? 1 : 2,
    priority_label: input.priorityLabel,
    notification_state: "queued",
    deliver_after: "2026-03-18T05:30:00.000Z",
    change_summary: {
      old: {
        value_time: input.beforeDate ? `${input.beforeDate}T${input.beforeTime || "23:59:00"}Z` : null,
        source_label: input.sourceLabelOld,
        source_kind: input.primarySource?.source_kind || null,
        source_observed_at: "2026-03-18T04:20:00.000Z",
      },
      new: {
        value_time: input.afterDate ? `${input.afterDate}T${input.afterTime || "23:59:00"}Z` : null,
        source_label: input.sourceLabelNew,
        source_kind: input.primarySource?.source_kind || null,
        source_observed_at: "2026-03-18T04:40:00.000Z",
      },
    },
    decision_support: buildDecisionSupport({
      changeType: input.changeType,
      intakePhase: input.intakePhase || "replay",
      primarySource: input.primarySource,
      label: input.label,
      beforeDate: input.beforeDate,
      afterDate: input.afterDate,
    }),
  };
}

function manualRow(
  entity_uid: string,
  family: CourseWorkItemFamily,
  event_name: string,
  ordinal: number | null,
  due_date: string,
  due_time: string | null,
): ManualEvent {
  return {
    entity_uid,
    lifecycle: "active",
    manual_support: true,
    family_id: family.id,
    family_name: family.canonical_label,
    course_display: family.course_display,
    course_dept: family.course_dept,
    course_number: family.course_number,
    course_suffix: family.course_suffix,
    course_quarter: family.course_quarter,
    course_year2: family.course_year2,
    raw_type: family.canonical_label,
    event_name,
    ordinal,
    due_date,
    due_time,
    time_precision: due_time ? "datetime" : "date_only",
    event: userFacingEvent(family.course_display, family.canonical_label, event_name, ordinal, due_date, due_time),
    created_at: nowIso,
    updated_at: nowIso,
  };
}

function buildEvidence(changes: ChangeItem[]): Record<string, EvidencePreviewResponse> {
  const out: Record<string, EvidencePreviewResponse> = {};
  for (const change of changes) {
    const after = change.after_event || change.before_event;
    out[`${change.id}:after`] = {
      side: "after",
      content_type: "text/plain",
      truncated: false,
      filename: `change-${change.id}-after.txt`,
      provider: change.primary_source?.provider || "gmail",
      structured_kind: change.primary_source?.provider === "ics" ? "ics_event" : "gmail_event",
      structured_items: after ? [{
        uid: after.uid || undefined,
        event_display: after.event_display,
        source_title: change.primary_source?.provider === "ics" ? "Canvas event card" : "Professor announcement",
        start_at: after.due_date ? `${after.due_date}T${after.due_time || "23:59:00"}Z` : null,
        end_at: after.due_date ? `${after.due_date}T${after.due_time || "23:59:00"}Z` : null,
        sender: change.primary_source?.provider === "gmail" ? "Professor <staff@example.edu>" : undefined,
        snippet: change.primary_source?.provider === "gmail" ? "Because of the room conflict, Homework 4 is now due Sunday at 11:59 PM." : undefined,
        internal_date: "2026-03-18T04:39:00.000Z",
        thread_id: "demo-thread-1",
      }] : [],
      event_count: after ? 1 : 0,
      events: [],
      preview_text: change.primary_source?.provider === "gmail"
        ? "Professor note: because of a room conflict, the item is now due later this week. Gradescope and rubric are unchanged."
        : "Canvas assignment due date changed on the authoritative course calendar.",
    };
    out[`${change.id}:before`] = {
      ...out[`${change.id}:after`],
      side: "before",
      filename: `change-${change.id}-before.txt`,
      preview_text: "Previous canonical timing before the newly observed update.",
    };
  }
  return out;
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function syncFamilyRawTypes() {
  demoState.families = demoState.families.map((family) => ({
    ...family,
    raw_types: demoState.rawTypes
      .filter((rawType) => rawType.family_id === family.id)
      .map((rawType) => rawType.raw_type)
      .sort((left, right) => left.localeCompare(right)),
    updated_at: nowIso,
  }));
}

function replaceFamilyRawTypes(familyId: number, nextRawTypes: string[]) {
  const family = demoState.families.find((item) => item.id === familyId);
  if (!family) {
    return;
  }
  demoState.rawTypes = demoState.rawTypes.filter((item) => item.family_id !== familyId);
  let nextId = Math.max(0, ...demoState.rawTypes.map((item) => item.id));
  for (const rawType of nextRawTypes) {
    nextId += 1;
    demoState.rawTypes.push(rawTypeRow(nextId, family, rawType));
  }
  syncFamilyRawTypes();
}

export function getDemoPreviewState() {
  return clone(demoState);
}

function buildDemoObservabilitySync(sourceId: number, phase: "bootstrap" | "replay", status: "RUNNING" | "SUCCEEDED" | "FAILED"): SourceObservabilitySync {
  const source = demoState.sources.find((row) => row.source_id === sourceId);
  return {
    request_id: `demo-${phase}-${sourceId}`,
    phase,
    trigger_type: phase === "bootstrap" ? "manual" : "scheduler",
    status,
    created_at: nowIso,
    updated_at: nowIso,
    stage: status === "RUNNING" ? "llm_parse" : "completed",
    substage: status === "RUNNING" ? "provider_reduce" : "completed",
    stage_updated_at: nowIso,
    applied: status === "SUCCEEDED",
    applied_at: status === "SUCCEEDED" ? nowIso : null,
    elapsed_ms: sourceId === 1 ? (phase === "bootstrap" ? 4620 : 480) : phase === "bootstrap" ? 18600 : 3290,
    error_code: status === "FAILED" ? source?.last_error_code || "attention" : null,
    error_message: status === "FAILED" ? source?.last_error_message || "Preview mode replay is blocked." : null,
    connector_result: { status: status === "FAILED" ? "error" : "changed", error_code: null, error_message: null },
    llm_usage: phase === "bootstrap"
      ? {
          total_tokens: sourceId === 1 ? 3990 : 30010,
          cached_input_tokens: sourceId === 1 ? 0 : 20110,
          latency_ms_total: sourceId === 1 ? 4620 : 18600,
        }
      : {
          total_tokens: sourceId === 1 ? 361 : 5260,
          cached_input_tokens: sourceId === 1 ? 0 : 3360,
          latency_ms_total: sourceId === 1 ? 480 : 3290,
        },
    progress: source?.sync_progress || null,
  };
}

function buildDemoSourceObservability(sourceId: number): SourceObservabilityResponse {
  if (sourceId === 1) {
    return {
      source_id: 1,
      active_request_id: null,
      bootstrap: {
        ...buildDemoObservabilitySync(1, "bootstrap", "SUCCEEDED"),
        connector_result: { provider: "ics", status: "CHANGED", records_count: 18, error_code: null, error_message: null },
      },
      bootstrap_summary: {
        imported_count: 18,
        review_required_count: 1,
        ignored_count: 2,
        conflict_count: 0,
        state: "review_required",
      },
      latest_replay: null,
      active: null,
      operator_guidance: null,
      source_product_phase: "needs_initial_review",
      source_recovery: {
        trust_state: "partial",
        impact_summary: "Imported baseline items are visible, but one item still needs Initial Review before this source is fully trusted for monitoring.",
        next_action: "wait",
        next_action_label: "Finish Initial Review",
        last_good_sync_at: "2026-03-18T05:05:00.000Z",
        degraded_since: "2026-03-18T05:05:00.000Z",
        recovery_steps: [
          "Review the remaining baseline item.",
          "Approve or reject it before relying on replay review.",
        ],
      },
    };
  }

  return {
    source_id: 2,
    active_request_id: "demo-replay-2",
    bootstrap: buildDemoObservabilitySync(2, "bootstrap", "SUCCEEDED"),
    bootstrap_summary: {
      imported_count: 9,
      review_required_count: 0,
      ignored_count: 6,
      conflict_count: 1,
      state: "completed",
    },
    latest_replay: buildDemoObservabilitySync(2, "replay", "FAILED"),
    active: buildDemoObservabilitySync(2, "replay", "RUNNING"),
    operator_guidance: {
      recommended_action: "investigate_runtime",
      severity: "warning",
      reason_code: "oauth_expired",
      message: "Reconnect Gmail before trusting replay.",
      related_request_id: "demo-replay-2",
      progress_age_seconds: 180,
    },
    source_product_phase: "needs_attention",
    source_recovery: {
      trust_state: "blocked",
      impact_summary: "New Gmail-based changes may be missing until the mailbox is reconnected.",
      next_action: "reconnect_gmail",
      next_action_label: "Reconnect Gmail",
      last_good_sync_at: "2026-03-17T04:40:00.000Z",
      degraded_since: "2026-03-18T04:58:00.000Z",
      recovery_steps: [
        "Reconnect the Gmail mailbox.",
        "Run a sync to confirm replay recovers.",
      ],
    },
  };
}

function buildDemoSourceSyncHistory(sourceId: number): SourceSyncHistoryResponse {
  return {
    source_id: sourceId,
    items:
      sourceId === 1
        ? [
            {
              ...buildDemoObservabilitySync(1, "bootstrap", "SUCCEEDED"),
              connector_result: { provider: "ics", status: "CHANGED", records_count: 18, error_code: null, error_message: null },
            },
          ]
        : [
            buildDemoObservabilitySync(2, "replay", "FAILED"),
            { ...buildDemoObservabilitySync(2, "replay", "SUCCEEDED"), request_id: "demo-replay-2-prev", status: "SUCCEEDED", error_code: null, error_message: null, updated_at: "2026-03-17T04:40:00.000Z" },
            { ...buildDemoObservabilitySync(2, "replay", "FAILED"), request_id: "demo-replay-2-prev-2", updated_at: "2026-03-16T04:30:00.000Z" },
          ],
  };
}

function laneToTool(lane: AgentRecommendedAction["lane"]) {
  return {
    sources: "review_sources",
    initial_review: "review_initial_review_changes",
    changes: "review_replay_changes",
    families: "review_families",
    manual: "review_manual",
  }[lane];
}

function buildWorkspaceBlockingConditions(summary: ChangesWorkbenchSummary): AgentBlockingCondition[] {
  const items: AgentBlockingCondition[] = [];
  if ((summary.sources.blocking_count || 0) > 0) {
    items.push({
      code: summary.sources.reason_code || "sources_attention_required",
      message: summary.sources.message,
      severity: "blocking",
    });
  }
  if ((summary.baseline_review_pending || 0) > 0) {
    items.push({
      code: "baseline_review_pending",
      message: "Baseline import review is not finished yet.",
      severity: "warning",
    });
  }
  return items;
}

function buildDemoWorkspaceAgentContext(): AgentWorkspaceContext {
  const workbench = clone(getDemoWorkspaceSummary());
  const nextAction = workbench.workspace_posture.next_action;
  return {
    generated_at: nowIso,
    summary: workbench,
    top_pending_changes: clone(
      demoState.changes
        .filter((row) => row.review_status === "pending")
        .slice(0, 3),
    ),
    recommended_next_action: {
      lane: nextAction.lane,
      label: nextAction.label,
      reason: nextAction.reason,
      reason_code: "demo.agent.workspace.next_action",
      reason_params: {},
      risk_level: workbench.workspace_posture.phase === "attention_required" ? "high" : workbench.workspace_posture.phase === "monitoring_live" ? "low" : "medium",
      recommended_tool: laneToTool(nextAction.lane),
    },
    blocking_conditions: buildWorkspaceBlockingConditions(workbench),
    available_next_tools: [
      laneToTool(nextAction.lane),
      "review_change_context",
      "review_source_context",
    ],
  };
}

function getDemoWorkspaceSummary(): ChangesWorkbenchSummary {
  const pending = demoState.changes.filter((row) => row.review_status === "pending" && row.review_bucket === "changes").length;
  const baselinePending = demoState.changes.filter((row) => row.review_status === "pending" && row.review_bucket === "initial_review").length;
  const baselineReviewed = demoState.changes.filter((row) => row.review_status !== "pending" && row.review_bucket === "initial_review").length;
  const baselineTotal = demoState.changes.filter((row) => row.review_bucket === "initial_review").length;
  const activeSources = demoState.sources.filter((row) => row.is_active);
  const attentionSources = activeSources.filter(
    (row) =>
      Boolean(row.last_error_message) ||
      row.operator_guidance?.severity === "warning" ||
      row.operator_guidance?.severity === "blocking" ||
      row.runtime_state === "rebind_pending",
  );
  const blockingSources = attentionSources.filter((row) => row.operator_guidance?.severity === "blocking");
  const pendingSuggestions = demoState.rawTypeSuggestions.filter((row) => row.status === "pending").length;
  const manualActiveCount = demoState.manualEvents.filter((row) => row.lifecycle !== "removed").length;
  const baselineImporting = activeSources.some((row) => row.source_product_phase === "importing_baseline");
  const workspacePhase =
    baselineImporting
      ? "baseline_import"
      : baselinePending > 0
        ? "initial_review"
        : attentionSources.length > 0
          ? "attention_required"
          : "monitoring_live";
  return {
    changes_pending: pending,
    baseline_review_pending: baselinePending,
    recommended_lane: baselinePending > 0 ? "initial_review" : pending > 0 ? "changes" : pendingSuggestions > 0 ? "families" : null,
    recommended_lane_reason_code:
      baselinePending > 0 ? "baseline_review_pending" : pending > 0 ? "changes_pending" : pendingSuggestions > 0 ? "family_governance_pending" : "all_clear",
    recommended_action_reason:
      baselinePending > 0
        ? `${baselinePending} baseline import items are waiting in Initial Review.`
        : pending > 0
          ? `${pending} pending change proposals are waiting for review decisions.`
          : pendingSuggestions > 0
            ? "Family or raw-type governance items need attention."
            : "No immediate lane action is required.",
    workspace_posture: {
      phase: workspacePhase,
      initial_review: {
        pending_count: baselinePending,
        reviewed_count: baselineReviewed,
        total_count: baselineTotal,
        completion_percent: baselineTotal > 0 ? Math.round((baselineReviewed / baselineTotal) * 100) : 100,
        completed_at: baselinePending === 0 && baselineTotal > 0 ? nowIso : null,
      },
      monitoring: {
        live_since: baselinePending === 0 ? "2026-03-18T05:05:00.000Z" : null,
        replay_active: pending > 0,
        active_source_count: activeSources.length,
      },
      next_action:
        workspacePhase === "baseline_import"
          ? {
              lane: "sources",
              label: "Open Sources",
              reason: "Baseline import is still running on at least one source.",
            }
          : workspacePhase === "initial_review"
            ? {
                lane: "initial_review",
                label: "Open Baseline Review",
                reason: baselinePending === 1 ? "1 baseline item still needs review." : `${baselinePending} baseline items still need review.`,
              }
            : workspacePhase === "attention_required"
              ? {
                  lane: "sources",
                  label: "Open Sources",
                  reason: "A source needs attention before the workspace is fully trustworthy.",
                }
              : pending > 0
                ? {
                    lane: "changes",
                    label: "Open Changes",
                    reason: pending === 1 ? "1 replay change is waiting." : `${pending} replay changes are waiting.`,
                  }
                : pendingSuggestions > 0
                  ? {
                      lane: "families",
                      label: "Open Families",
                      reason: "Naming drift is waiting in Families.",
                    }
                  : {
                      lane: "manual",
                      label: "Open Manual",
                      reason: manualActiveCount > 0 ? "Manual fallback work is still open." : "No immediate action is required.",
                    },
    },
    sources: {
      active_count: activeSources.length,
      running_count: activeSources.filter((row) => row.sync_state === "running").length,
      queued_count: activeSources.filter((row) => row.sync_state === "queued").length,
      attention_count: attentionSources.length,
      blocking_count: blockingSources.length,
      recommended_action: blockingSources.length > 0 ? "investigate_runtime" : attentionSources.length > 0 ? "continue_review_with_caution" : "continue_review",
      severity: blockingSources.length > 0 ? "blocking" : attentionSources.length > 0 ? "warning" : "info",
      reason_code: blockingSources.length > 0 ? "latest_sync_failed" : attentionSources.length > 0 ? "sync_running" : "source_idle",
      message:
        blockingSources.length > 0
          ? "A source needs runtime attention before lane state is fully trustworthy."
          : attentionSources.length > 0
            ? "Some sources still need attention while you continue review."
            : "No active sync is running. Continue reviewing changes.",
      related_request_id: attentionSources[0]?.active_request_id || null,
      progress_age_seconds: null,
    },
    families: {
      attention_count: pendingSuggestions,
      pending_raw_type_suggestions: pendingSuggestions,
      mappings_state: demoState.familyStatus.state,
      last_rebuilt_at: demoState.familyStatus.last_rebuilt_at,
      last_error: demoState.familyStatus.last_error,
    },
    manual: {
      active_event_count: manualActiveCount,
      lane_role: "fallback",
    },
    generated_at: nowIso,
  };
}

function buildDemoChangeAgentContext(changeId: number): AgentChangeContext {
  const change = demoState.changes.find((row) => row.id === changeId);
  if (!change) {
    throw new Error("Change not found");
  }
  const decisionSupport = change.decision_support;
  const suggestedAction = decisionSupport?.suggested_action || "review_carefully";
  return {
    generated_at: nowIso,
    change: clone(change),
    recommended_next_action: {
      lane: change.review_bucket,
      label:
        suggestedAction === "approve"
          ? "Approve change"
          : suggestedAction === "reject"
            ? "Reject change"
            : suggestedAction === "edit"
              ? "Edit before approval"
              : "Review carefully",
      reason: decisionSupport?.suggested_action_reason || "",
      reason_code: "demo.agent.change.next_action",
      reason_params: {},
      risk_level: (decisionSupport?.risk_level || "medium") as AgentRecommendedAction["risk_level"],
      recommended_tool:
        suggestedAction === "approve" || suggestedAction === "reject"
          ? "submit_change_decision"
          : suggestedAction === "edit"
            ? "preview_change_edit"
            : "view_change",
    },
    blocking_conditions: [
      ...(change.review_status !== "pending"
        ? [{ code: "change_already_reviewed", message: "This change has already been reviewed.", severity: "blocking" as const }]
        : []),
      ...((decisionSupport?.risk_level || "") === "high"
        ? [{ code: "high_risk_change", message: decisionSupport?.risk_summary || "This change should be reviewed carefully before confirmation.", severity: "warning" as const }]
        : []),
    ],
    available_next_tools: ["view_change", "view_before_evidence", "view_after_evidence", "submit_change_decision", "preview_change_edit", "preview_label_learning", "review_families"],
  };
}

function buildDemoSourceAgentContext(sourceId: number): AgentSourceContext {
  const source = demoState.sources.find((row) => row.source_id === sourceId);
  if (!source) throw new Error("Source not found");
  const observability = buildDemoSourceObservability(sourceId);
  const nextAction = observability.source_recovery?.next_action || "wait";
  return {
    generated_at: nowIso,
    source: clone({ ...source, user_id: demoState.user.id }),
    observability: clone(observability),
    active_sync_request:
      sourceId === 2
        ? {
            request_id: "demo-replay-2",
            source_id: 2,
            trigger_type: "scheduler",
            status: "RUNNING",
            idempotency_key: "demo-replay-2",
            trace_id: "demo-replay-2",
            error_code: null,
            error_message: null,
            metadata: {},
            created_at: nowIso,
            updated_at: nowIso,
            stage: "llm_parse",
            substage: "provider_reduce",
            stage_updated_at: nowIso,
            connector_result: null,
            llm_usage: null,
            elapsed_ms: 3290,
            applied: false,
            applied_at: null,
            progress: source.sync_progress || null,
          }
        : null,
    recommended_next_action: {
      lane: "sources",
      label:
        observability.source_recovery?.next_action_label ||
        (nextAction === "retry_sync"
          ? "Run another sync"
          : nextAction === "reconnect_gmail"
            ? "Reconnect source"
            : nextAction === "update_ics"
              ? "Open connection flow"
              : "Wait for runtime"),
      reason: observability.source_recovery?.impact_summary || observability.operator_guidance?.message || "",
      reason_code: "demo.agent.source.next_action",
      reason_params: {},
      risk_level:
        observability.source_recovery?.trust_state === "blocked"
          ? "high"
          : observability.source_recovery?.trust_state === "partial" || observability.source_recovery?.trust_state === "stale"
            ? "medium"
            : "low",
      recommended_tool:
        nextAction === "retry_sync"
          ? "run_source_sync"
          : nextAction === "reconnect_gmail"
            ? "reconnect_source"
            : "review_source_observability",
    },
    blocking_conditions: [
      ...(observability.operator_guidance?.severity === "blocking"
        ? [{ code: observability.operator_guidance.reason_code, message: observability.operator_guidance.message, severity: "blocking" as const }]
        : []),
      ...(observability.source_recovery?.trust_state === "blocked" || observability.source_recovery?.trust_state === "partial" || observability.source_recovery?.trust_state === "stale"
        ? [{ code: "source_recovery_attention", message: observability.source_recovery?.impact_summary || "Source trust is degraded.", severity: observability.source_recovery?.trust_state === "blocked" ? "blocking" as const : "warning" as const }]
        : []),
    ],
    available_next_tools: ["review_source_observability", "view_sync_history", "run_source_sync", "start_oauth_session"],
  };
}

function nextProposalId() {
  return Math.max(0, ...demoState.agentProposals.map((item) => item.proposal_id)) + 1;
}

function createDemoChangeProposal(changeId: number): AgentProposal {
  const context = buildDemoChangeAgentContext(changeId);
  const action = context.change.decision_support?.suggested_action || "review_carefully";
  const payload =
    action === "approve" || action === "reject"
      ? { kind: "change_decision", change_id: changeId, decision: action }
      : action === "edit"
        ? { kind: "web_only_change_edit_required", change_id: changeId }
        : { kind: "web_only_high_risk_change_review", change_id: changeId };
  const proposal: AgentProposal = {
    proposal_id: nextProposalId(),
    owner_user_id: 1,
    proposal_type: "change_decision",
    status: "open",
    target_kind: "change",
    target_id: String(changeId),
    summary:
      action === "approve"
        ? "Approve this change."
        : action === "reject"
          ? "Reject this change."
          : action === "edit"
            ? "Open web edit flow before approving this change."
            : "Review this high-risk change carefully.",
    summary_code: `demo.agent.change.${action}.summary`,
    reason: context.recommended_next_action.reason,
    reason_code: context.recommended_next_action.reason_code,
    risk_level: context.recommended_next_action.risk_level,
    confidence: action === "review_carefully" ? 0.56 : action === "edit" ? 0.78 : 0.92,
    suggested_action: action,
    origin_kind: "web",
    origin_label: "embedded_agent",
    origin_request_id: null,
    lifecycle_code: "agents.proposal.lifecycle.open",
    execution_mode:
      payload.kind === "change_decision" ? "approval_ticket_required" : "web_only",
    execution_mode_code:
      payload.kind === "change_decision"
        ? "agents.proposal.execution_mode.approval_ticket_required"
        : "agents.proposal.execution_mode.web_only",
    next_step_code:
      payload.kind === "change_decision"
        ? "agents.proposal.next_step.create_ticket"
        : "agents.proposal.next_step.open_web_flow",
    can_create_ticket: payload.kind === "change_decision",
    suggested_payload: payload,
    context: { recommended_next_action: context.recommended_next_action, blocking_conditions: context.blocking_conditions },
    target_snapshot: {
      change_id: changeId,
      review_status: context.change.review_status,
      review_bucket: context.change.review_bucket,
      intake_phase: context.change.intake_phase,
      detected_at: context.change.detected_at,
    },
    expires_at: "2026-03-19T05:20:00.000Z",
    created_at: nowIso,
    updated_at: nowIso,
  };
  demoState.agentProposals.unshift(proposal);
  return proposal;
}

function createDemoSourceProposal(sourceId: number): AgentProposal {
  const context = buildDemoSourceAgentContext(sourceId);
  const action = context.observability.source_recovery?.next_action || "wait";
  const payload =
    action === "retry_sync"
      ? { kind: "run_source_sync", source_id: sourceId }
      : action === "reconnect_gmail"
        ? { kind: "reconnect_source", source_id: sourceId, provider: context.source.provider }
        : action === "update_ics"
          ? { kind: "update_source_settings", source_id: sourceId, provider: context.source.provider }
          : { kind: "wait_for_runtime", source_id: sourceId };
  const proposal: AgentProposal = {
    proposal_id: nextProposalId(),
    owner_user_id: 1,
    proposal_type: "source_recovery",
    status: "open",
    target_kind: "source",
    target_id: String(sourceId),
    summary:
      action === "retry_sync"
        ? "Run another sync for this source."
        : action === "reconnect_gmail"
          ? "Reconnect this source before trusting it again."
          : action === "update_ics"
            ? "Update source settings before the next sync."
            : "Wait for runtime progress before taking further action.",
    summary_code: `demo.agent.source.${action}.summary`,
    reason: context.recommended_next_action.reason,
    reason_code: context.recommended_next_action.reason_code,
    risk_level: context.recommended_next_action.risk_level,
    confidence: action === "retry_sync" ? 0.82 : action === "wait" ? 0.62 : 0.74,
    suggested_action: action,
    origin_kind: "web",
    origin_label: "embedded_agent",
    origin_request_id: null,
    lifecycle_code: "agents.proposal.lifecycle.open",
    execution_mode: payload.kind === "run_source_sync" ? "approval_ticket_required" : "web_only",
    execution_mode_code:
      payload.kind === "run_source_sync"
        ? "agents.proposal.execution_mode.approval_ticket_required"
        : "agents.proposal.execution_mode.web_only",
    next_step_code:
      payload.kind === "run_source_sync"
        ? "agents.proposal.next_step.create_ticket"
        : "agents.proposal.next_step.open_web_flow",
    can_create_ticket: payload.kind === "run_source_sync",
    suggested_payload: payload,
    context: { recommended_next_action: context.recommended_next_action, blocking_conditions: context.blocking_conditions },
    target_snapshot: {
      source_id: sourceId,
      active_request_id: context.source.active_request_id,
      runtime_state: context.source.runtime_state,
      source_product_phase: context.source.source_product_phase,
      trust_state: context.observability.source_recovery?.trust_state || null,
    },
    expires_at: "2026-03-18T17:20:00.000Z",
    created_at: nowIso,
    updated_at: nowIso,
  };
  demoState.agentProposals.unshift(proposal);
  return proposal;
}

function nextApprovalTicket(proposal: AgentProposal): ApprovalTicket {
  return {
    ticket_id: `demo-ticket-${Date.now()}`,
    proposal_id: proposal.proposal_id,
    owner_user_id: proposal.owner_user_id,
    channel: "web",
    action_type: String(proposal.suggested_payload.kind || proposal.suggested_action),
    target_kind: proposal.target_kind,
    target_id: proposal.target_id,
    payload: proposal.suggested_payload,
    payload_hash: `demo-hash-${proposal.proposal_id}`,
    target_snapshot: proposal.target_snapshot,
    risk_level: proposal.risk_level,
    origin_kind: proposal.origin_kind,
    origin_label: "create_approval_ticket",
    origin_request_id: proposal.origin_request_id,
    status: "open",
    lifecycle_code: "agents.ticket.lifecycle.open",
    next_step_code: "agents.ticket.next_step.confirm_or_cancel",
    confirm_summary_code: `agents.ticket.confirm.${String(proposal.suggested_payload.kind || proposal.suggested_action)}.summary`,
    cancel_summary_code: `agents.ticket.cancel.${String(proposal.suggested_payload.kind || proposal.suggested_action)}.summary`,
    transition_message_code: `agents.ticket.transition.${String(proposal.suggested_payload.kind || proposal.suggested_action)}.waiting_confirm`,
    social_safe_cta_code: proposal.risk_level === "low" ? "agents.ticket.cta.confirm" : null,
    can_confirm: true,
    can_cancel: true,
    last_transition_kind: "web",
    last_transition_label: "create_approval_ticket",
    executed_result: {},
    expires_at: proposal.expires_at,
    confirmed_at: null,
    canceled_at: null,
    executed_at: null,
    created_at: nowIso,
    updated_at: nowIso,
  };
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function parseBody(init?: RequestInit) {
  if (!init?.body || typeof init.body !== "string") {
    return null;
  }
  try {
    return JSON.parse(init.body);
  } catch {
    return null;
  }
}

function pathKey(path: string) {
  const url = new URL(path, "http://demo.local");
  return { url, pathname: url.pathname };
}

export async function demoBackendFetch<T>(path: string, init?: RequestInit): Promise<T> {
  await delay(120);
  const method = (init?.method || "GET").toUpperCase();
  const body = parseBody(init);
  const { url, pathname } = pathKey(path);

  if (pathname === "/auth/login" || pathname === "/auth/register") {
    return clone({
      user: {
        id: 9001,
        email: demoState.user.email || "demo@calendardiff.app",
        language_code: demoState.user.language_code,
        timezone_name: demoState.user.timezone_name,
        timezone_source: demoState.user.timezone_source,
        created_at: demoState.user.created_at || nowIso,
        onboarding_stage: "ready",
        first_source_id: 1,
      },
    }) as T;
  }
  if (pathname === "/auth/logout") {
    return { logged_out: true } as T;
  }
  if (pathname === "/auth/session") {
    return clone({
      user: {
        id: 9001,
        email: demoState.user.email || "demo@calendardiff.app",
        language_code: demoState.user.language_code,
        timezone_name: demoState.user.timezone_name,
        timezone_source: demoState.user.timezone_source,
        created_at: demoState.user.created_at || nowIso,
        onboarding_stage: "ready",
        first_source_id: 1,
      },
    }) as T;
  }
  if (pathname === "/onboarding/status") {
    return clone(demoState.onboarding) as T;
  }
  if (pathname === "/onboarding/canvas-ics") {
    return clone(demoState.onboarding) as T;
  }
  if (pathname === "/onboarding/gmail/oauth-sessions") {
    return {
      source_id: 2,
      provider: "gmail",
      authorization_url: "#demo-oauth",
      expires_at: nowIso,
    } as T;
  }
  if (pathname === "/onboarding/gmail-skip") {
    demoState.onboarding.gmail_skipped = true;
    return clone(demoState.onboarding) as T;
  }
  if (pathname === "/onboarding/term-binding") {
    return clone(demoState.onboarding) as T;
  }
  if (pathname === "/agent/context/workspace" && method === "GET") {
    return clone(buildDemoWorkspaceAgentContext()) as T;
  }
  if (/^\/agent\/context\/changes\/\d+$/.test(pathname) && method === "GET") {
    const changeId = Number(pathname.split("/").pop());
    return clone(buildDemoChangeAgentContext(changeId)) as T;
  }
  if (/^\/agent\/context\/sources\/\d+$/.test(pathname) && method === "GET") {
    const sourceId = Number(pathname.split("/").pop());
    return clone(buildDemoSourceAgentContext(sourceId)) as T;
  }
  if (pathname === "/agent/proposals/change-decision" && method === "POST") {
    return clone(createDemoChangeProposal(Number(body?.change_id))) as T;
  }
  if (pathname === "/agent/proposals/source-recovery" && method === "POST") {
    return clone(createDemoSourceProposal(Number(body?.source_id))) as T;
  }
  if (/^\/agent\/proposals\/\d+$/.test(pathname) && method === "GET") {
    const proposalId = Number(pathname.split("/").pop());
    const proposal = demoState.agentProposals.find((item) => item.proposal_id === proposalId);
    if (!proposal) throw new Error("Agent proposal not found");
    return clone(proposal) as T;
  }
  if (pathname === "/agent/approval-tickets" && method === "POST") {
    const proposalId = Number(body?.proposal_id);
    const proposal = demoState.agentProposals.find((item) => item.proposal_id === proposalId);
    if (!proposal) throw new Error("Agent proposal not found");
    const kind = String(proposal.suggested_payload.kind || "");
    if (!["change_decision", "run_source_sync"].includes(kind)) {
      throw new Error("This proposal is not directly executable and must stay in the web workflow.");
    }
    const ticket = nextApprovalTicket(proposal);
    demoState.approvalTickets.unshift(ticket);
    return clone(ticket) as T;
  }
  if (/^\/agent\/approval-tickets\/[^/]+$/.test(pathname) && method === "GET") {
    const ticketId = decodeURIComponent(pathname.split("/").pop() || "");
    const ticket = demoState.approvalTickets.find((item) => item.ticket_id === ticketId);
    if (!ticket) throw new Error("Approval ticket not found");
    return clone(ticket) as T;
  }
  if (/^\/agent\/approval-tickets\/[^/]+\/confirm$/.test(pathname) && method === "POST") {
    const ticketId = pathname.split("/")[3];
    const ticket = demoState.approvalTickets.find((item) => item.ticket_id === ticketId);
    if (!ticket) throw new Error("Approval ticket not found");
    const kind = String(ticket.payload.kind || "");
    if (kind === "change_decision") {
      const row = demoState.changes.find((item) => item.id === Number(ticket.payload.change_id));
      if (row) {
        row.review_status = ticket.payload.decision === "reject" ? "rejected" : "approved";
        row.reviewed_at = nowIso;
      }
      ticket.executed_result = {
        kind,
        change_id: Number(ticket.payload.change_id),
        decision: String(ticket.payload.decision || "approve"),
        review_status: row?.review_status || "approved",
      };
    }
    if (kind === "run_source_sync") {
      const source = demoState.sources.find((item) => item.source_id === Number(ticket.payload.source_id));
      if (source) {
        source.sync_state = "running";
        source.runtime_state = "running";
        source.active_request_id = `agent-sync-${source.source_id}`;
      }
      ticket.executed_result = {
        kind,
        source_id: Number(ticket.payload.source_id),
        request_id: `agent-sync-${ticket.payload.source_id}`,
        status: "QUEUED",
      };
    }
    ticket.status = "executed";
    ticket.confirmed_at = nowIso;
    ticket.executed_at = nowIso;
    ticket.updated_at = nowIso;
    const proposal = demoState.agentProposals.find((item) => item.proposal_id === ticket.proposal_id);
    if (proposal) proposal.status = "accepted";
    return clone(ticket) as T;
  }
  if (/^\/agent\/approval-tickets\/[^/]+\/cancel$/.test(pathname) && method === "POST") {
    const ticketId = pathname.split("/")[3];
    const ticket = demoState.approvalTickets.find((item) => item.ticket_id === ticketId);
    if (!ticket) throw new Error("Approval ticket not found");
    ticket.status = "canceled";
    ticket.canceled_at = nowIso;
    ticket.updated_at = nowIso;
    const proposal = demoState.agentProposals.find((item) => item.proposal_id === ticket.proposal_id);
    if (proposal) proposal.status = "rejected";
    return clone(ticket) as T;
  }
  if (pathname === "/changes/summary") {
    return clone(getDemoWorkspaceSummary()) as T;
  }
  if (pathname === "/changes" && method === "GET") {
    const reviewStatus = (url.searchParams.get("review_status") || "pending").toLowerCase();
    const reviewBucket = (url.searchParams.get("review_bucket") || "all").toLowerCase();
    const intakePhase = (url.searchParams.get("intake_phase") || "all").toLowerCase();
    const sourceId = url.searchParams.get("source_id");
    let rows = demoState.changes.slice();
    if (reviewStatus !== "all") {
      rows = rows.filter((row) => row.review_status === reviewStatus);
    }
    if (reviewBucket !== "all") {
      rows = rows.filter((row) => row.review_bucket === reviewBucket);
    }
    if (intakePhase !== "all") {
      rows = rows.filter((row) => row.intake_phase === intakePhase);
    }
    if (sourceId) {
      rows = rows.filter((row) => row.primary_source?.source_id === Number(sourceId));
    }
    return clone(rows) as T;
  }
  if (/^\/changes\/\d+$/.test(pathname) && method === "GET") {
    const changeId = Number(pathname.split("/").pop());
    return clone(demoState.changes.find((row) => row.id === changeId) || null) as T;
  }
  if (/^\/changes\/\d+\/views$/.test(pathname) && method === "PATCH") {
    const changeId = Number(pathname.split("/")[2]);
    const row = demoState.changes.find((item) => item.id === changeId);
    if (!row) throw new Error("Review change not found");
    row.viewed_at = nowIso;
    row.viewed_note = body?.note || null;
    return clone(row) as T;
  }
  if (/^\/changes\/\d+\/decisions$/.test(pathname) && method === "POST") {
    const changeId = Number(pathname.split("/")[2]);
    const row = demoState.changes.find((item) => item.id === changeId);
    if (!row) throw new Error("Review change not found");
    row.review_status = body?.decision === "reject" ? "rejected" : "approved";
    row.reviewed_at = nowIso;
    row.review_note = body?.note || null;
    return clone({
      id: row.id,
      review_status: row.review_status,
      reviewed_at: row.reviewed_at,
      review_note: row.review_note,
      idempotent: false,
    }) as T;
  }
  if (pathname === "/changes/batch/decisions" && method === "POST") {
    const ids = Array.isArray(body?.ids) ? body.ids.map(Number) : [];
    let succeeded = 0;
    for (const id of ids) {
      const row = demoState.changes.find((item) => item.id === id);
      if (!row) continue;
      row.review_status = body?.decision === "reject" ? "rejected" : "approved";
      row.reviewed_at = nowIso;
      row.review_note = body?.note || null;
      succeeded += 1;
    }
    const response: ChangeBatchDecisionResponse = {
      decision: body?.decision === "reject" ? "reject" : "approve",
      total_requested: ids.length,
      succeeded,
      failed: ids.length - succeeded,
      results: ids.map((id: number) => ({
        id,
        ok: demoState.changes.some((item) => item.id === id),
        review_status: demoState.changes.find((item) => item.id === id)?.review_status as "pending" | "approved" | "rejected" | null,
        idempotent: false,
        reviewed_at: nowIso,
        review_note: body?.note || null,
        error_code: demoState.changes.some((item) => item.id === id) ? null : "not_found",
        error_detail: demoState.changes.some((item) => item.id === id) ? null : "Missing demo row",
      })),
    };
    return clone(response) as T;
  }
  if (/^\/changes\/\d+\/edit-context$/.test(pathname) && method === "GET") {
    const changeId = Number(pathname.split("/")[2]);
    const row = demoState.changes.find((item) => item.id === changeId);
    if (!row || !row.after_event) throw new Error("Review change not found");
    const editable: ChangeEditContext = {
      change_id: row.id,
      entity_uid: row.entity_uid,
      editable_event: {
        uid: row.after_event.uid || row.entity_uid,
        family_name: row.after_event.event_display.family_name,
        course_dept: row.after_event.event_display.course_display.split(" ")[0] || "CSE",
        course_number: Number(row.after_event.event_display.course_display.split(" ")[1]?.replace(/\D/g, "") || "120"),
        course_suffix: null,
        course_quarter: "WI",
        course_year2: 26,
        raw_type: row.after_event.event_display.family_name,
        event_name: row.after_event.event_display.display_label,
        ordinal: row.after_event.event_display.ordinal,
        due_date: row.after_event.due_date || null,
        due_time: row.after_event.due_time || null,
        time_precision: row.after_event.time_precision === "date_only" ? "date_only" : "datetime",
      },
    };
    return clone(editable) as T;
  }
  if (/^\/changes\/\d+\/evidence\/(before|after)\/preview$/.test(pathname) && method === "GET") {
    const match = pathname.match(/^\/changes\/(\d+)\/evidence\/(before|after)\/preview$/);
    const key = `${match?.[1]}:${match?.[2]}`;
    return clone(demoState.evidence[key]) as T;
  }
  if (pathname === "/changes/edits/preview" && method === "POST") {
    const request = body as ChangeEditRequest;
    const changeId = request?.target?.change_id;
    const row = demoState.changes.find((item) => item.id === changeId);
    if (!row || !row.after_event) throw new Error("Review change not found");
    const next = clone(row.after_event);
    if (request.patch.event_name) {
      next.event_display.display_label = request.patch.event_name;
    }
    if (request.patch.due_date !== undefined) {
      next.due_date = request.patch.due_date;
    }
    if (request.patch.due_time !== undefined) {
      next.due_time = request.patch.due_time;
    }
    if (request.patch.time_precision) {
      next.time_precision = request.patch.time_precision;
    }
    const response: ChangeEditPreviewResponse = {
      mode: request.mode,
      entity_uid: row.entity_uid,
      change_id: row.id,
      proposal_change_type: "due_changed",
      base: clone(row.after_event),
      candidate_after: next,
      delta_seconds: 86400,
      will_reject_pending_change_ids: [],
      idempotent: false,
    };
    return response as T;
  }
  if (pathname === "/changes/edits" && method === "POST") {
    const request = body as ChangeEditRequest;
    const changeId = request?.target?.change_id;
    const row = demoState.changes.find((item) => item.id === changeId);
    if (!row || !row.after_event) throw new Error("Review change not found");
    if (request.patch.event_name) row.after_event.event_display.display_label = request.patch.event_name;
    if (request.patch.due_date !== undefined) row.after_event.due_date = request.patch.due_date;
    if (request.patch.due_time !== undefined) row.after_event.due_time = request.patch.due_time;
    if (request.patch.time_precision) row.after_event.time_precision = request.patch.time_precision;
    const response: ChangeEditApplyResponse = {
      mode: request.mode,
      applied: true,
      idempotent: false,
      entity_uid: row.entity_uid,
      edited_change_id: row.id,
      canonical_edit_change_id: request.mode === "canonical" ? row.id + 1000 : null,
      rejected_pending_change_ids: [],
      event: clone(row.after_event),
    };
    return response as T;
  }
  if (/^\/changes\/\d+\/label-learning\/preview$/.test(pathname) && method === "POST") {
    const changeId = Number(pathname.split("/")[2]);
    const row = demoState.changes.find((item) => item.id === changeId);
    const preview: LabelLearningPreview = {
      change_id: changeId,
      course_display: row?.after_event?.event_display.course_display || null,
      course_dept: "CSE",
      course_number: 120,
      course_suffix: null,
      course_quarter: "WI",
      course_year2: 26,
      raw_label: row?.after_event?.event_display.display_label || "Homework 4",
      ordinal: row?.after_event?.event_display.ordinal || 4,
      status: "unresolved",
      families: clone(demoState.families.filter((family) => family.course_display === row?.after_event?.event_display.course_display).slice(0, 3)),
    };
    return preview as T;
  }
  if (/^\/changes\/\d+\/label-learning$/.test(pathname) && method === "POST") {
    const changeId = Number(pathname.split("/")[2]);
    const row = demoState.changes.find((item) => item.id === changeId);
    const response: LabelLearningApplyResponse = {
      applied: true,
      course_display: row?.after_event?.event_display.course_display || null,
      course_dept: "CSE",
      course_number: 120,
      course_suffix: null,
      course_quarter: "WI",
      course_year2: 26,
      raw_label: row?.after_event?.event_display.display_label || null,
      family_id: body?.family_id || 11,
      canonical_label: body?.canonical_label || demoState.families.find((family) => family.id === (body?.family_id || 11))?.canonical_label || "Homework",
      approved_change_id: changeId,
    };
    return response as T;
  }
  if (pathname === "/families" && method === "GET") {
    return clone(demoState.families) as T;
  }
  if (pathname === "/families" && method === "POST") {
    const nextId = Math.max(...demoState.families.map((item) => item.id)) + 1;
    const rawTypes = Array.isArray(body?.raw_types) ? body.raw_types.filter((item: unknown) => typeof item === "string" && item.trim()) : [];
    const next: CourseWorkItemFamily = {
      id: nextId,
      course_display: `${body?.course_dept || "NEW"} ${body?.course_number || 1}${body?.course_suffix || ""} ${body?.course_quarter || ""}${body?.course_year2 || ""}`.trim(),
      course_dept: body?.course_dept || "NEW",
      course_number: Number(body?.course_number || 1),
      course_suffix: body?.course_suffix || null,
      course_quarter: body?.course_quarter || null,
      course_year2: body?.course_year2 || null,
      canonical_label: body?.canonical_label || "New Family",
      raw_types: rawTypes,
      created_at: nowIso,
      updated_at: nowIso,
    };
    demoState.families.unshift(next);
    replaceFamilyRawTypes(next.id, rawTypes);
    return clone(next) as T;
  }
  if (/^\/families\/\d+$/.test(pathname) && method === "PATCH") {
    const familyId = Number(pathname.split("/").pop());
    const family = demoState.families.find((item) => item.id === familyId);
    if (!family) throw new Error("Family not found");
    family.canonical_label = body?.canonical_label || family.canonical_label;
    family.updated_at = nowIso;
    if (Array.isArray(body?.raw_types)) {
      replaceFamilyRawTypes(
        familyId,
        body.raw_types.filter((item: unknown) => typeof item === "string" && item.trim()),
      );
    } else {
      syncFamilyRawTypes();
    }
    return clone(demoState.families.find((item) => item.id === familyId) || family) as T;
  }
  if (pathname === "/families/status") {
    return clone(demoState.familyStatus) as T;
  }
  if (pathname === "/families/courses") {
    const courses: CourseIdentity[] = demoState.families.map((family) => ({
      course_display: family.course_display,
      course_dept: family.course_dept,
      course_number: family.course_number,
      course_suffix: family.course_suffix,
      course_quarter: family.course_quarter,
      course_year2: family.course_year2,
    }));
    return { courses } as T;
  }
  if (pathname === "/families/raw-types" && method === "GET") {
    const familyId = url.searchParams.get("family_id");
    const courseDept = url.searchParams.get("course_dept");
    const courseNumber = url.searchParams.get("course_number");
    const rows = demoState.rawTypes.filter((rawType) => {
      if (familyId && rawType.family_id !== Number(familyId)) return false;
      if (courseDept && rawType.course_dept !== courseDept) return false;
      if (courseNumber && rawType.course_number !== Number(courseNumber)) return false;
      return true;
    });
    return clone(rows) as T;
  }
  if (pathname === "/families/raw-types/relink" && method === "POST") {
    const rawTypeId = Number(body?.raw_type_id);
    const familyId = Number(body?.family_id);
    const rawType = demoState.rawTypes.find((item) => item.id === rawTypeId);
    const targetFamily = demoState.families.find((item) => item.id === familyId);
    if (!rawType || !targetFamily) {
      throw new Error("Raw type relink target not found");
    }
    const previousFamilyId = rawType.family_id;
    rawType.family_id = targetFamily.id;
    rawType.course_display = targetFamily.course_display;
    rawType.course_dept = targetFamily.course_dept;
    rawType.course_number = targetFamily.course_number;
    rawType.course_suffix = targetFamily.course_suffix;
    rawType.course_quarter = targetFamily.course_quarter;
    rawType.course_year2 = targetFamily.course_year2;
    rawType.updated_at = nowIso;
    syncFamilyRawTypes();
    return clone({
      raw_type_id: rawType.id,
      family_id: rawType.family_id,
      previous_family_id: previousFamilyId,
      course_display: targetFamily.course_display,
      course_dept: targetFamily.course_dept,
      course_number: targetFamily.course_number,
      course_suffix: targetFamily.course_suffix,
      course_quarter: targetFamily.course_quarter,
      course_year2: targetFamily.course_year2,
    }) as T;
  }
  if (pathname === "/families/raw-type-suggestions" && method === "GET") {
    const status = (url.searchParams.get("status") || "pending").toLowerCase();
    const limit = Number(url.searchParams.get("limit") || "50");
    const rows = demoState.rawTypeSuggestions
      .filter((item) => (status === "all" ? true : item.status === status))
      .slice(0, Number.isFinite(limit) ? limit : 50);
    return clone(rows) as T;
  }
  if (/^\/families\/raw-type-suggestions\/\d+\/decisions$/.test(pathname) && method === "POST") {
    const suggestionId = Number(pathname.split("/")[3]);
    const suggestion = demoState.rawTypeSuggestions.find((item) => item.id === suggestionId);
    if (!suggestion) throw new Error("Raw type suggestion not found");
    const decision = body?.decision === "approve" || body?.decision === "reject" || body?.decision === "dismiss" ? body.decision : "reject";
    suggestion.status = decision === "approve" ? "approved" : decision === "reject" ? "rejected" : "dismissed";
    suggestion.review_note = body?.note || null;
    suggestion.reviewed_at = nowIso;
    suggestion.updated_at = nowIso;
    if (decision === "approve" && suggestion.source_raw_type && suggestion.suggested_family_id) {
      const rawType = demoState.rawTypes.find((item) => item.raw_type === suggestion.source_raw_type && item.family_id === suggestion.source_family_id);
      const targetFamily = demoState.families.find((item) => item.id === suggestion.suggested_family_id);
      if (rawType && targetFamily) {
        rawType.family_id = targetFamily.id;
        rawType.course_display = targetFamily.course_display;
        rawType.course_dept = targetFamily.course_dept;
        rawType.course_number = targetFamily.course_number;
        rawType.course_suffix = targetFamily.course_suffix;
        rawType.course_quarter = targetFamily.course_quarter;
        rawType.course_year2 = targetFamily.course_year2;
        rawType.updated_at = nowIso;
        syncFamilyRawTypes();
      }
    }
    const response: RawTypeSuggestionDecisionResponse = {
      id: suggestion.id,
      status: suggestion.status,
      review_note: suggestion.review_note || null,
      reviewed_at: suggestion.reviewed_at || null,
    };
    return clone(response) as T;
  }
  if (pathname === "/settings/profile" && method === "GET") {
    return clone(demoState.user) as T;
  }
  if (pathname === "/settings/profile" && method === "PATCH") {
    demoState.user = { ...demoState.user, ...(body || {}) };
    return clone(demoState.user) as T;
  }
  if (pathname === "/settings/mcp-tokens" && method === "GET") {
    return clone(demoState.mcpTokens) as T;
  }
  if (pathname === "/settings/mcp-tokens" && method === "POST") {
    const tokenId = `mcp_tok_${Date.now()}`;
    const expiresInDays =
      typeof body?.expires_in_days === "number" && Number.isFinite(body.expires_in_days)
        ? body.expires_in_days
        : 30;
    const createdAt = nowIso;
    const expiresAt = new Date(new Date(createdAt).getTime() + expiresInDays * 24 * 60 * 60 * 1000).toISOString();
    const row: McpAccessToken = {
      token_id: tokenId,
      label: typeof body?.label === "string" && body.label.trim() ? body.label.trim() : "MCP token",
      scopes: ["calendar.read", "changes.write", "manual.write"],
      last_used_at: null,
      expires_at: expiresAt,
      revoked_at: null,
      created_at: createdAt,
    };
    demoState.mcpTokens.unshift(row);
    const response: McpAccessTokenCreateResponse = {
      ...row,
      token: `cdiff_mcp_demo_${Date.now().toString(36)}`,
    };
    return clone(response) as T;
  }
  if (/^\/settings\/mcp-tokens\/[^/]+$/.test(pathname) && method === "DELETE") {
    const tokenId = decodeURIComponent(pathname.split("/").pop() || "");
    const token = demoState.mcpTokens.find((item) => item.token_id === tokenId);
    if (!token) throw new Error("MCP token not found");
    token.revoked_at = nowIso;
    return clone(token) as T;
  }
  if (pathname === "/manual/events" && method === "GET") {
    const includeRemoved = url.searchParams.get("include_removed") === "true";
    return clone(includeRemoved ? demoState.manualEvents : demoState.manualEvents.filter((row) => row.lifecycle !== "removed")) as T;
  }
  if (pathname === "/manual/events" && method === "POST") {
    const family = demoState.families.find((item) => item.id === body?.family_id) || demoState.families[0];
    const next = manualRow(
      `man-${Date.now()}`,
      family,
      body?.event_name || "Manual Event",
      body?.ordinal || null,
      body?.due_date || "2026-03-28",
      body?.time_precision === "date_only" ? null : body?.due_time || "23:59:00",
    );
    demoState.manualEvents.unshift(next);
    const response: ManualEventMutationResponse = {
      applied: true,
      idempotent: false,
      change_id: 9900,
      entity_uid: next.entity_uid,
      lifecycle: next.lifecycle,
      event: next,
    };
    return response as T;
  }
  if (/^\/manual\/events\/[^/]+$/.test(pathname) && method === "PATCH") {
    const entityUid = decodeURIComponent(pathname.split("/").pop() || "");
    const event = demoState.manualEvents.find((item) => item.entity_uid === entityUid);
    if (!event) throw new Error("Manual event not found");
    event.event_name = body?.event_name || event.event_name;
    event.raw_type = body?.raw_type || event.raw_type;
    event.ordinal = body?.ordinal ?? event.ordinal;
    event.due_date = body?.due_date || event.due_date;
    event.due_time = body?.time_precision === "date_only" ? null : (body?.due_time || event.due_time);
    event.time_precision = body?.time_precision || event.time_precision;
    event.updated_at = nowIso;
    return {
      applied: true,
      idempotent: false,
      change_id: 9901,
      entity_uid: event.entity_uid,
      lifecycle: event.lifecycle,
      event: clone(event),
    } as T;
  }
  if (/^\/manual\/events\/[^/]+$/.test(pathname) && method === "DELETE") {
    const entityUid = decodeURIComponent(pathname.split("/").pop() || "");
    const event = demoState.manualEvents.find((item) => item.entity_uid === entityUid);
    if (!event) throw new Error("Manual event not found");
    event.lifecycle = "removed";
    event.updated_at = nowIso;
    return {
      applied: true,
      idempotent: false,
      change_id: 9902,
      entity_uid: event.entity_uid,
      lifecycle: event.lifecycle,
      event: clone(event),
    } as T;
  }
  if (/^\/sources\/\d+\/observability$/.test(pathname) && method === "GET") {
    const sourceId = Number(pathname.split("/")[2]);
    return clone(buildDemoSourceObservability(sourceId)) as T;
  }
  if (/^\/sources\/\d+\/sync-history$/.test(pathname) && method === "GET") {
    const sourceId = Number(pathname.split("/")[2]);
    return clone(buildDemoSourceSyncHistory(sourceId)) as T;
  }
  if (pathname === "/sources" && method === "GET") {
    const status = url.searchParams.get("status") || "active";
    const rows =
      status === "archived"
        ? demoState.sources.filter((row) => !row.is_active)
        : status === "all"
          ? demoState.sources
          : demoState.sources.filter((row) => row.is_active);
    return clone(rows) as T;
  }
  if (/^\/sources\/\d+$/.test(pathname) && method === "PATCH") {
    const sourceId = Number(pathname.split("/").pop());
    const source = demoState.sources.find((item) => item.source_id === sourceId);
    if (!source) throw new Error("Source not found");
    if (typeof body?.is_active === "boolean") source.is_active = body.is_active;
    source.last_error_message = null;
    source.last_error_code = null;
    source.updated_at = nowIso;
    return clone(source) as T;
  }
  if (/^\/sources\/\d+$/.test(pathname) && method === "DELETE") {
    const sourceId = Number(pathname.split("/").pop());
    const source = demoState.sources.find((item) => item.source_id === sourceId);
    if (!source) throw new Error("Source not found");
    source.is_active = false;
    source.lifecycle_state = "archived";
    return { deleted: true } as T;
  }
  if (/^\/sources\/\d+\/sync-requests$/.test(pathname) && method === "POST") {
    return {
      request_id: `demo-sync-${Date.now()}`,
    } as T;
  }
  if (/^\/sync-requests\/.+$/.test(pathname) && method === "GET") {
    const requestId = pathname.split("/").pop() || "demo-sync";
    const response: SyncStatus = {
      request_id: requestId,
      source_id: 1,
      status: "running",
      applied: false,
      error_code: null,
      error_message: null,
      connector_result: { status: "changed", error_code: null, error_message: null },
      progress: {
        phase: "fetch",
        label: "Polling source",
        detail: "Preview mode simulated sync",
        current: 2,
        total: 4,
        percent: 50,
        unit: "steps",
      },
    };
    return response as T;
  }
  if (/^\/sources\/\d+\/oauth-sessions$/.test(pathname) && method === "POST") {
    return {
      source_id: Number(pathname.split("/")[2]),
      provider: "gmail",
      authorization_url: "#demo-oauth",
      expires_at: nowIso,
    } as T;
  }

  throw new Error(`Preview mode does not yet implement ${method} ${pathname}`);
}

export type { DemoState };
