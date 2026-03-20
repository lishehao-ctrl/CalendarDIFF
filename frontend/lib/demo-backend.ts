"use client";

import type {
  ChangesWorkbenchSummary,
  CourseIdentity,
  CourseWorkItemFamily,
  CourseWorkItemFamilyStatus,
  CourseWorkItemRawType,
  EvidencePreviewResponse,
  LabelLearningApplyResponse,
  LabelLearningPreview,
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
    }),
  ];

  return {
    user: {
      id: 9001,
      email: null,
      notify_email: "demo@calendardiff.app",
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
}) : ChangeItem {
  const ordinal = Number((input.label.match(/(\d+)/)?.[1] || "0")) || null;
  return {
    id: input.id,
    entity_uid: `demo-change-${input.id}`,
    change_type: input.changeType,
    change_origin: "ingest_proposal",
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
      bootstrap: buildDemoObservabilitySync(1, "bootstrap", "SUCCEEDED"),
      latest_replay: buildDemoObservabilitySync(1, "replay", "SUCCEEDED"),
      active: null,
      operator_guidance: null,
    };
  }

  return {
    source_id: 2,
    active_request_id: "demo-replay-2",
    bootstrap: buildDemoObservabilitySync(2, "bootstrap", "SUCCEEDED"),
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
  };
}

function buildDemoSourceSyncHistory(sourceId: number): SourceSyncHistoryResponse {
  return {
    source_id: sourceId,
    items:
      sourceId === 1
        ? [
            buildDemoObservabilitySync(1, "replay", "SUCCEEDED"),
            { ...buildDemoObservabilitySync(1, "replay", "SUCCEEDED"), request_id: "demo-replay-1-prev", updated_at: "2026-03-17T04:50:00.000Z" },
          ]
        : [
            buildDemoObservabilitySync(2, "replay", "FAILED"),
            { ...buildDemoObservabilitySync(2, "replay", "SUCCEEDED"), request_id: "demo-replay-2-prev", status: "SUCCEEDED", error_code: null, error_message: null, updated_at: "2026-03-17T04:40:00.000Z" },
            { ...buildDemoObservabilitySync(2, "replay", "FAILED"), request_id: "demo-replay-2-prev-2", updated_at: "2026-03-16T04:30:00.000Z" },
          ],
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
        notify_email: demoState.user.notify_email || "demo@calendardiff.app",
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
        notify_email: demoState.user.notify_email || "demo@calendardiff.app",
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
  if (pathname === "/changes/summary") {
    const pending = demoState.changes.filter((row) => row.review_status === "pending").length;
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
    const summary: ChangesWorkbenchSummary = {
      changes_pending: pending,
      recommended_lane: pending > 0 ? "changes" : pendingSuggestions > 0 ? "families" : null,
      recommended_lane_reason_code:
        pending > 0 ? "changes_pending" : pendingSuggestions > 0 ? "family_governance_pending" : "all_clear",
      recommended_action_reason:
        pending > 0
          ? `${pending} pending change proposals are waiting for review decisions.`
          : pendingSuggestions > 0
            ? "Family or raw-type governance items need attention."
            : "No immediate lane action is required.",
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
    return summary as T;
  }
  if (pathname === "/changes" && method === "GET") {
    const reviewStatus = (url.searchParams.get("review_status") || "pending").toLowerCase();
    const sourceId = url.searchParams.get("source_id");
    let rows = demoState.changes.slice();
    if (reviewStatus !== "all") {
      rows = rows.filter((row) => row.review_status === reviewStatus);
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
