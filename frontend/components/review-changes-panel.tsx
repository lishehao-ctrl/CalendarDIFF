"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CalendarRange, CheckCheck, ChevronDown, ChevronUp, Eye, FileSearch, PencilLine, Sparkles, SquarePen, XCircle } from "lucide-react";
import { ChangeAgentCard } from "@/components/change-agent-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { Sheet, SheetContent, SheetDescription, SheetDismissButton, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { WorkbenchLoadingShell } from "@/components/workbench-loading-shell";
import {
  applyChangeLabelLearning,
  batchDecideChanges,
  changesListCacheKey,
  changesSummaryCacheKey,
  decideChange,
  getChangesSummary,
  getChangeEditContext,
  listChanges,
  markChangeViewed,
  previewChangeEvidence,
  previewChangeLabelLearning,
} from "@/lib/api/changes";
import { listSources, sourceListCacheKey } from "@/lib/api/sources";
import { withBasePath } from "@/lib/demo-mode";
import { useResponsiveTier } from "@/lib/use-responsive-tier";
import { workbenchQueueRowClassName } from "@/lib/workbench-styles";
import {
  formatDateTime,
  formatSemanticDue,
  formatStatusLabel,
  sourceDescriptor,
  sourceKindDescriptor,
  summarizeChange,
} from "@/lib/presenters";
import { translate } from "@/lib/i18n/runtime";
import type { EvidencePreviewResponse, LabelLearningPreview, ChangesWorkbenchSummary, ChangeItem, ChangeEditContext, SourceRow } from "@/lib/types";
import { useApiResource } from "@/lib/use-api-resource";

const statusOptions = ["pending", "approved", "rejected", "all"] as const;

type Banner = {
  tone: "info" | "error";
  text: string;
} | null;

type ChangeSummarySide = NonNullable<ChangeItem["change_summary"]>["old"];
type EvidenceViewMode = "summary" | "raw";
type CompactWorkspaceSection = "evidence" | "match" | "extras";

type LoadedEvidence = {
  payload: EvidencePreviewResponse;
  summaryFallback: string;
};

type StructuredEvidenceItem = EvidencePreviewResponse["structured_items"][number];

function getEvidenceAvailability(change: ChangeItem) {
  return {
    before: change.evidence_availability?.before ?? Boolean(change.before_event || change.before_display),
    after: change.evidence_availability?.after ?? Boolean(change.after_event || change.after_display),
  };
}

function defaultEvidenceSide(change: ChangeItem): "before" | "after" {
  const availability = getEvidenceAvailability(change);
  if (availability.after) return "after";
  if (availability.before) return "before";
  return "after";
}

function groupChangesByCourse(rows: ChangeItem[]) {
  const groups = new Map<string, ChangeItem[]>();
  for (const row of rows) {
    const course = row.after_event?.event_display.course_display || row.before_event?.event_display.course_display || translate("changes.unknownCourse");
    if (!groups.has(course)) {
      groups.set(course, []);
    }
    groups.get(course)!.push(row);
  }
  return Array.from(groups.entries())
    .map(([course, changes]) => ({
      course,
      changes: changes.sort((left, right) => {
        const leftPriority = left.priority_rank ?? Number.MAX_SAFE_INTEGER;
        const rightPriority = right.priority_rank ?? Number.MAX_SAFE_INTEGER;
        if (leftPriority !== rightPriority) return leftPriority - rightPriority;
        return new Date(right.detected_at).getTime() - new Date(left.detected_at).getTime();
      }),
    }))
    .sort((left, right) => {
      if (right.changes.length !== left.changes.length) return right.changes.length - left.changes.length;
      return left.course.localeCompare(right.course);
    });
}

function ChangeSummarySourceCard({
  title,
  emptyLabel,
  summary,
}: {
  title: string;
  emptyLabel: string;
  summary: ChangeSummarySide | null | undefined;
}) {
  const sourceLabel = summary?.source_label || emptyLabel;
  const sourceKind = sourceKindDescriptor(summary?.source_kind);

  return (
    <div className="rounded-[1.1rem] border border-line/80 bg-white/75 p-4 text-sm text-[#314051]">
      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{title}</p>
      <p className="mt-2 font-medium text-ink">{sourceLabel}</p>
      {sourceKind ? <p className="mt-1 text-xs text-[#6d7885]">{sourceKind}</p> : null}
      <div className="mt-4 space-y-1.5 text-sm text-[#314051]">
        <p>Value time: {formatDateTime(summary?.value_time, "N/A")}</p>
        {summary?.source_observed_at ? <p>Observed: {formatDateTime(summary.source_observed_at)}</p> : null}
      </div>
    </div>
  );
}

function ReviewInboxError({ message, basePath = "" }: { message: string; basePath?: string }) {
  const showSourcesCta = message.includes("Connect at least one active source in Sources");
  return (
    <ErrorState
      message={message}
      actionLabel={showSourcesCta ? translate("overview.cards.sources.open") : undefined}
      actionHref={showSourcesCta ? withBasePath(basePath, "/sources") : undefined}
    />
  );
}

function EvidenceField({ label, value, truncate = false }: { label: string; value?: string | null; truncate?: boolean }) {
  if (!value) {
    return null;
  }
  return (
    <p className={truncate ? "truncate" : undefined}>
      <span className="text-[#6d7885]">{label}:</span> {value}
    </p>
  );
}

function renderFallbackStructuredItems(evidence: LoadedEvidence): StructuredEvidenceItem[] {
  return (evidence.payload.events || []).map((event) => ({
    uid: event.uid,
    source_title: event.summary,
    start_at: event.dtstart,
    end_at: event.dtend,
    location: event.location,
    description: event.description,
    url: event.url,
  }));
}

function EvidenceSummary({ evidence }: { evidence: LoadedEvidence }) {
  const structuredItems = evidence.payload.structured_items?.length ? evidence.payload.structured_items : renderFallbackStructuredItems(evidence);

  if (structuredItems.length === 0) {
    return <p className="text-sm text-[#596270]">{translate("changes.workspace.evidenceSummaryUnavailable")}</p>;
  }

  if (evidence.payload.structured_kind === "gmail_event") {
    return (
      <div className="space-y-3">
        {structuredItems.map((item, index) => (
          <div key={`${item.uid || "gmail"}-${index}`} className="rounded-[1.15rem] border border-line/80 bg-white/75 p-4 text-sm text-[#314051]">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-medium text-ink">{item.event_display?.display_label || translate("common.labels.unknown")}</p>
                  {item.source_title ? <Badge tone="info">{item.source_title}</Badge> : null}
                </div>
                {item.uid ? <p className="mt-1 text-xs text-[#6d7885]">UID: {item.uid}</p> : null}
              </div>
              <Badge tone="approved">{translate("changes.workspace.emailBacked")}</Badge>
            </div>
            <div className="mt-4 grid gap-2 md:grid-cols-2">
              <p>{translate("changes.workspace.due")}: {formatDateTime(item.start_at, "N/A")}</p>
              <p>{translate("changes.workspace.ends")}: {formatDateTime(item.end_at, "N/A")}</p>
              <EvidenceField label={translate("changes.workspace.sender")} value={item.sender} />
              <p>{translate("changes.workspace.received")}: {formatDateTime(item.internal_date, translate("common.labels.unknown"))}</p>
              <EvidenceField label={translate("changes.workspace.thread")} value={item.thread_id} />
            </div>
            {item.snippet ? (
              <div className="mt-4 rounded-[1rem] border border-line/70 bg-white/80 p-3">
                <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("changes.workspace.mailSummary")}</p>
                <p className="mt-2 whitespace-pre-wrap leading-6 text-[#596270]">{item.snippet}</p>
              </div>
            ) : null}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {structuredItems.map((item, index) => (
        <div key={`${item.uid || "event"}-${index}`} className="rounded-[1.15rem] border border-line/80 bg-white/75 p-4 text-sm text-[#314051]">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-medium text-ink">{item.event_display?.display_label || translate("common.labels.unknown")}</p>
                {item.source_title ? <Badge tone="info">{item.source_title}</Badge> : null}
              </div>
              {item.uid ? <p className="mt-1 text-xs text-[#6d7885]">UID: {item.uid}</p> : null}
            </div>
            <Badge tone="info">Event {index + 1}</Badge>
          </div>
          <div className="mt-4 grid gap-2 md:grid-cols-2">
            <p>{translate("changes.workspace.start")}: {formatDateTime(item.start_at, "N/A")}</p>
            <p>{translate("changes.workspace.end")}: {formatDateTime(item.end_at, "N/A")}</p>
            <EvidenceField label={translate("changes.workspace.location")} value={item.location} />
            {item.url ? (
              <p className="truncate">
                <span className="text-[#6d7885]">{translate("changes.workspace.link")}:</span>{" "}
                <a className="text-cobalt underline-offset-4 hover:underline" href={item.url} target="_blank" rel="noreferrer">
                  {item.url}
                </a>
              </p>
            ) : null}
          </div>
          {item.description ? <p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-[#596270]">{item.description}</p> : null}
        </div>
      ))}
    </div>
  );
}

function useWorkspaceLayout() {
  const { isMobile, isDesktop } = useResponsiveTier();
  return {
    side: (isMobile ? "bottom" : "right") as "right" | "bottom",
    isDesktop,
    isMobile,
    showInlineWorkspace: !isMobile,
  };
}

function changeTypeTone(changeType: string | null | undefined) {
  if (changeType === "removed") {
    return "error";
  }
  if (changeType === "created") {
    return "approved";
  }
  if (changeType === "updated" || changeType === "due_changed") {
    return "pending";
  }
  return "info";
}

function priorityTone(priorityLabel: string | null | undefined) {
  if (!priorityLabel) {
    return "default";
  }
  const normalized = priorityLabel.toLowerCase();
  if (normalized.includes("high") || normalized.includes("urgent")) {
    return "error";
  }
  if (normalized.includes("normal") || normalized.includes("medium")) {
    return "pending";
  }
  return "info";
}

function confidenceLabel(row: ChangeItem) {
  const value = row.proposal_sources.reduce<number | null>((highest, source) => {
    if (typeof source.confidence !== "number") {
      return highest;
    }
    return highest === null ? source.confidence : Math.max(highest, source.confidence);
  }, null);

  if (value === null) {
    return translate("changes.confidenceNeedsReview");
  }

  return translate("changes.confidencePercent", { percent: Math.round(value * 100) });
}

function canonicalDisplayLabel(context: ChangeEditContext | null, row: ChangeItem) {
  if (context?.editable_event?.family_name) {
    return context.editable_event.family_name;
  }
  return row.after_event?.event_display.family_name || row.before_event?.event_display.family_name || translate("changes.noCanonicalFamilyYet");
}

function canonicalTimelineLabel(context: ChangeEditContext | null) {
  if (!context) {
    return null;
  }

  const { editable_event: event } = context;
  const parts = [event.event_name || event.raw_type || null, formatSemanticDue(event as unknown as Record<string, unknown>, ""), event.raw_type || null]
    .filter((value, index, array) => Boolean(value) && array.indexOf(value) === index)
    .join(" · ");

  return parts || null;
}

function suggestedActionLabel(value: ChangeItem["decision_support"] extends { suggested_action: infer T } ? T : string | null | undefined) {
  switch (value) {
    case "approve":
      return translate("changes.suggestions.approve");
    case "reject":
      return translate("changes.suggestions.reject");
    case "edit":
      return translate("changes.suggestions.edit");
    case "review_carefully":
      return translate("changes.suggestions.reviewCarefully");
    default:
      return translate("changes.suggestions.notProvided");
  }
}

function suggestedActionTone(value: ChangeItem["decision_support"] extends { suggested_action: infer T } ? T : string | null | undefined) {
  switch (value) {
    case "approve":
      return "approved";
    case "reject":
      return "error";
    case "edit":
      return "pending";
    case "review_carefully":
      return "info";
    default:
      return "info";
  }
}

function riskTone(value: ChangeItem["decision_support"] extends { risk_level: infer T } ? T : string | null | undefined) {
  switch (value) {
    case "high":
      return "error";
    case "medium":
      return "pending";
    case "low":
      return "approved";
    default:
      return "info";
  }
}

function actionPreviewText(selected: ChangeItem, key: "approve" | "reject" | "edit") {
  if (selected.decision_support?.outcome_preview?.[key]) {
    return selected.decision_support.outcome_preview[key];
  }
  if (key === "approve") {
    return translate("changes.actionPreview.approve");
  }
  if (key === "reject") {
    return translate("changes.actionPreview.reject");
  }
  return translate("changes.actionPreview.edit");
}

function CompactSection({
  title,
  summary,
  open,
  onToggle,
  children,
}: {
  title: string;
  summary?: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <Card className="animate-surface-enter overflow-hidden p-0">
      <button type="button" onClick={onToggle} className="flex w-full items-center justify-between gap-4 px-4 py-4 text-left">
        <div>
          <p className="text-sm font-medium text-ink">{title}</p>
          {summary ? <p className="mt-1 text-xs text-[#6d7885]">{summary}</p> : null}
        </div>
        {open ? <ChevronUp className="h-4 w-4 text-[#6d7885]" /> : <ChevronDown className="h-4 w-4 text-[#6d7885]" />}
      </button>
      {open ? <div className="animate-section-enter border-t border-line/80 p-4">{children}</div> : null}
    </Card>
  );
}

function ChangeInboxRow({
  row,
  selected,
  checked,
  onToggleSelection,
  onOpen,
  showSelection,
  compact,
  basePath = "",
}: {
  row: ChangeItem;
  selected: boolean;
  checked: boolean;
  onToggleSelection: (checked: boolean) => void;
  onOpen: () => void;
  showSelection: boolean;
  compact: boolean;
  basePath?: string;
}) {
  const summary = summarizeChange(row);
  const beforeDue = formatSemanticDue((row.before_event || {}) as Record<string, unknown>, translate("changes.noPreviousTime"));
  const afterDue = formatSemanticDue((row.after_event || {}) as Record<string, unknown>, translate("changes.noNewTime"));
  const primarySource = row.primary_source ? sourceDescriptor(row.primary_source) : row.proposal_sources[0] ? sourceDescriptor(row.proposal_sources[0]) : translate("changes.needsSourceConfirmation");

  return (
    <div
      className={workbenchQueueRowClassName({
        selected,
        checked,
        className: "animate-surface-enter p-4",
      })}
    >
      <div className="flex items-start gap-3">
        {showSelection ? (
          <div className="pt-1">
            <Checkbox
              aria-label={`Select review change ${row.id}`}
              checked={checked}
              onChange={(event) => onToggleSelection(event.currentTarget.checked)}
            />
          </div>
        ) : null}
        <div className="min-w-0 flex-1">
          <button type="button" onClick={onOpen} className="w-full text-left">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={row.review_status}>{formatStatusLabel(row.review_status)}</Badge>
              {!row.viewed_at ? <Badge tone="pending">{translate("changes.new")}</Badge> : null}
              {!compact ? <Badge tone={changeTypeTone(row.change_type)}>{formatStatusLabel(row.change_type)}</Badge> : null}
              {!compact && row.priority_label ? <Badge tone={priorityTone(row.priority_label)}>{formatStatusLabel(row.priority_label)}</Badge> : null}
            </div>
            <h3 className="mt-3 text-base font-semibold text-ink">{summary.title}</h3>
            <p className="mt-2 text-sm leading-6 text-[#596270]">
              {beforeDue} {"→"} {afterDue}
            </p>
            <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-[#6d7885]">
              <span>{primarySource}</span>
              {!compact ? (
                <>
                  <span>•</span>
                  <span>{confidenceLabel(row)}</span>
                  <span>•</span>
                  <span>{row.viewed_at ? translate("changes.viewedAt", { time: formatDateTime(row.viewed_at) }) : translate("changes.newInInbox")}</span>
                </>
              ) : (
                <>
                  <span>•</span>
                  <span>{row.review_status === "pending" ? translate("changes.needsDecision") : translate("changes.reviewed")}</span>
                </>
              )}
            </div>
          </button>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button size="sm" variant={selected ? "secondary" : "soft"} onClick={onOpen}>
              <Eye className="mr-2 h-4 w-4" />
              {selected ? translate("changes.decisionOpen") : translate("changes.openDecision")}
            </Button>
            {!compact ? (
            <Button asChild size="sm" variant="ghost">
              <Link href={withBasePath(basePath, `/changes/${row.id}/canonical`)}>
                <SquarePen className="mr-2 h-4 w-4" />
                {translate("changes.editThenApprove")}
              </Link>
            </Button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

type DecisionWorkspaceProps = {
  selected: ChangeItem;
  currentEvidenceSide: "before" | "after";
  evidenceView: EvidenceViewMode;
  evidence: LoadedEvidence | null;
  previewBusy: "before" | "after" | null;
  labelLearning: LabelLearningPreview | null;
  labelLearningBusy: "preview" | "apply" | null;
  labelLearningError: string | null;
  learningOpen: boolean;
  newFamilyLabel: string;
  editContext: ChangeEditContext | null;
  editContextBusy: boolean;
  editContextError: string | null;
  decisionBusy: "approve" | "reject" | null;
  onMarkViewed: () => void;
  onEvidenceSideChange: (side: "before" | "after") => void;
  onEvidenceViewChange: (view: EvidenceViewMode) => void;
  onDecide: (decision: "approve" | "reject") => void;
  onLearningToggle: () => void;
  onApproveAndLearnExisting: (familyId: number, label: string, canonicalLabel: string) => void;
  onApproveAndLearnCreate: () => void;
  onNewFamilyLabelChange: (value: string) => void;
  onRetryLearningContext: () => void;
  basePath?: string;
  compact?: boolean;
};

function DecisionWorkspaceMain({
  selected,
  currentEvidenceSide,
  evidenceView,
  evidence,
  previewBusy,
  editContext,
  editContextBusy,
  editContextError,
  onEvidenceSideChange,
  onEvidenceViewChange,
  basePath = "",
  compact = false,
}: Pick<
  DecisionWorkspaceProps,
  | "selected"
  | "currentEvidenceSide"
  | "evidenceView"
  | "evidence"
  | "previewBusy"
  | "editContext"
  | "editContextBusy"
  | "editContextError"
  | "onEvidenceSideChange"
  | "onEvidenceViewChange"
  | "basePath"
  | "compact"
>) {
  const summary = summarizeChange(selected);
  const selectedEvidenceAvailability = getEvidenceAvailability(selected);
  const beforeDue = formatSemanticDue((selected.before_event || {}) as Record<string, unknown>, translate("changes.noPreviousTime"));
  const afterDue = formatSemanticDue((selected.after_event || {}) as Record<string, unknown>, translate("changes.noNewTime"));
  const canonicalTimeline = canonicalTimelineLabel(editContext);
  const decisionSupport = selected.decision_support;
  const [expandedSections, setExpandedSections] = useState<Record<CompactWorkspaceSection, boolean>>({
    evidence: false,
    match: false,
    extras: false,
  });

  useEffect(() => {
    setExpandedSections({
      evidence: false,
      match: false,
      extras: false,
    });
  }, [selected.id]);

  const evidenceSummary = `${selected.proposal_sources.length} source${selected.proposal_sources.length === 1 ? "" : "s"} · ${confidenceLabel(selected)}`;
  const evidenceBody = (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant={currentEvidenceSide === "before" ? "secondary" : "ghost"}
          onClick={() => onEvidenceSideChange("before")}
          disabled={!selectedEvidenceAvailability.before}
        >
          <FileSearch className="mr-2 h-4 w-4" />
          {previewBusy === "before" ? translate("changes.loading") : translate("changes.workspace.previewBefore")}
        </Button>
        <Button
          size="sm"
          variant={currentEvidenceSide === "after" ? "secondary" : "ghost"}
          onClick={() => onEvidenceSideChange("after")}
          disabled={!selectedEvidenceAvailability.after}
        >
          <CalendarRange className="mr-2 h-4 w-4" />
          {previewBusy === "after" ? translate("changes.loading") : translate("changes.workspace.previewAfter")}
        </Button>
      </div>
      {!selectedEvidenceAvailability.before || !selectedEvidenceAvailability.after ? (
        <p className="text-xs text-[#6d7885]">
          {selectedEvidenceAvailability.before && !selectedEvidenceAvailability.after
            ? translate("changes.workspace.onlyBeforeEvidence")
            : !selectedEvidenceAvailability.before && selectedEvidenceAvailability.after
              ? translate("changes.workspace.onlyAfterEvidence")
              : translate("changes.workspace.noEvidence")}
        </p>
      ) : null}
      <div className="inline-flex flex-wrap gap-2 rounded-full border border-line/80 bg-white/60 p-2">
        <Button size="sm" variant={evidenceView === "summary" ? "primary" : "ghost"} onClick={() => onEvidenceViewChange("summary")}>
          {translate("changes.workspace.summary")}
        </Button>
        <Button size="sm" variant={evidenceView === "raw" ? "primary" : "ghost"} onClick={() => onEvidenceViewChange("raw")}>
          {translate("changes.workspace.raw")}
        </Button>
      </div>
      <div className="rounded-[1.2rem] border border-line/80 bg-[#f2ebe1] p-4">
        {evidence ? (
          evidenceView === "summary" ? (
            <EvidenceSummary evidence={evidence} />
          ) : (
            <pre className="whitespace-pre-wrap text-xs leading-6 text-[#314051]">{evidence.payload.preview_text || evidence.summaryFallback}</pre>
          )
        ) : (
          <p className="text-sm text-[#596270]">{translate("changes.workspace.chooseEvidence")}</p>
        )}
      </div>
    </div>
  );

  const canonicalBody = (
    <div className="space-y-3">
      <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
        <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("changes.workspace.family")}</p>
        <p className="mt-2 text-sm font-medium text-ink">{canonicalDisplayLabel(editContext, selected)}</p>
      </div>
      <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
        <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("changes.workspace.canonicalEvent")}</p>
        <p className="mt-2 text-sm font-medium text-ink">
          {editContextError
            ? translate("changes.workspace.canonicalUnavailable")
            : canonicalTimeline || (editContextBusy ? translate("changes.workspace.canonicalLoading") : translate("changes.workspace.canonicalMissing"))}
        </p>
        {editContextError ? <p className="mt-2 text-xs leading-5 text-[#7f3d2a]">{editContextError}</p> : null}
      </div>
    </div>
  );

  return (
    <div className="space-y-4">
      <Card className={compact ? "p-4" : "p-5"}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("changes.workspace.title")}</p>
            <h2 className={`mt-2 font-semibold text-ink ${compact ? "text-xl" : "text-2xl"}`}>{summary.title}</h2>
            <p className="mt-2 text-sm leading-6 text-[#596270]">
              {selected.primary_source ? sourceDescriptor(selected.primary_source) : translate("changes.needsSourceConfirmation")} · {confidenceLabel(selected)}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge tone={selected.review_status}>{formatStatusLabel(selected.review_status)}</Badge>
            <Badge tone={changeTypeTone(selected.change_type)}>{formatStatusLabel(selected.change_type)}</Badge>
            {selected.priority_label ? <Badge tone={priorityTone(selected.priority_label)}>{formatStatusLabel(selected.priority_label)}</Badge> : null}
          </div>
        </div>
      </Card>

      {decisionSupport ? (
        <Card className={compact ? "p-4" : "p-5"}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("changes.workspace.decisionSupport")}</p>
            <div className="flex flex-wrap gap-2">
              <Badge tone={suggestedActionTone(decisionSupport.suggested_action)}>
                {suggestedActionLabel(decisionSupport.suggested_action)}
              </Badge>
              <Badge tone={riskTone(decisionSupport.risk_level)}>{formatStatusLabel(decisionSupport.risk_level)}</Badge>
            </div>
          </div>
          <div className={`mt-4 grid gap-3 ${compact ? "sm:grid-cols-1" : "md:grid-cols-2"}`}>
            <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
              <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("changes.workspace.whySeeingThis")}</p>
              <p className="mt-2 text-sm leading-6 text-[#314051]">{decisionSupport.why_now}</p>
            </div>
            <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
              <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("changes.workspace.suggestedAction")}</p>
              <p className="mt-2 text-sm font-medium text-ink">{suggestedActionLabel(decisionSupport.suggested_action)}</p>
              <p className="mt-2 text-sm leading-6 text-[#314051]">{decisionSupport.suggested_action_reason}</p>
            </div>
            <div className={`rounded-[1.15rem] border border-line/80 bg-white/72 p-4 ${compact ? "" : "md:col-span-2"}`}>
              <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("changes.workspace.risk")}</p>
              <p className="mt-2 text-sm font-medium text-ink">{formatStatusLabel(decisionSupport.risk_level)}</p>
              <p className="mt-2 text-sm leading-6 text-[#314051]">{decisionSupport.risk_summary}</p>
            </div>
          </div>
          {decisionSupport.key_facts.length > 0 ? (
            <div className="mt-4 rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
              <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("changes.workspace.keyFacts")}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {decisionSupport.key_facts.map((fact) => (
                  <span key={fact} className="rounded-full border border-line/80 bg-white/80 px-3 py-1.5 text-sm text-[#314051]">
                    {fact}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
        </Card>
      ) : null}

      <Card className={compact ? "p-4" : "p-5"}>
        <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("changes.workspace.whatChanged")}</p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("changes.workspace.before")}</p>
            <p className="mt-2 text-sm font-medium text-ink">{beforeDue}</p>
          </div>
          <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("changes.workspace.after")}</p>
            <p className="mt-2 text-sm font-medium text-ink">{afterDue}</p>
          </div>
          <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("changes.workspace.detected")}</p>
            <p className="mt-2 text-sm font-medium text-ink">{formatDateTime(selected.detected_at)}</p>
          </div>
          <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("changes.workspace.primarySource")}</p>
            <p className="mt-2 text-sm font-medium text-ink">{selected.primary_source ? sourceDescriptor(selected.primary_source) : translate("changes.needsSourceConfirmation")}</p>
          </div>
        </div>
        <div className={`mt-4 grid gap-3 ${compact ? "sm:grid-cols-1" : "xl:grid-cols-2"}`}>
          <ChangeSummarySourceCard
            title={translate("changes.workspace.before")}
            emptyLabel={translate("changes.noPreviousTime")}
            summary={selected.change_summary?.old}
          />
          <ChangeSummarySourceCard
            title={translate("changes.workspace.after")}
            emptyLabel={translate("changes.noNewTime")}
            summary={selected.change_summary?.new}
          />
        </div>
      </Card>
      {compact ? (
        <CompactSection
          title={decisionSupport ? translate("changes.workspace.evidence") : translate("changes.workspace.evidenceFallbackTitle")}
          summary={evidenceSummary}
          open={expandedSections.evidence}
          onToggle={() => setExpandedSections((current) => ({ ...current, evidence: !current.evidence }))}
        >
          {evidenceBody}
        </CompactSection>
      ) : (
        <Card className="p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">
                {decisionSupport ? translate("changes.workspace.evidence") : translate("changes.workspace.evidenceFallbackTitle")}
              </p>
              <p className="mt-2 text-sm text-[#596270]">{evidenceSummary}</p>
            </div>
          </div>
          <div className="mt-4">{evidenceBody}</div>
        </Card>
      )}

      {compact ? (
        <CompactSection
          title={translate("changes.workspace.canonicalMatch")}
          summary={canonicalDisplayLabel(editContext, selected)}
          open={expandedSections.match}
          onToggle={() => setExpandedSections((current) => ({ ...current, match: !current.match }))}
        >
          {canonicalBody}
        </CompactSection>
      ) : (
        <Card className="p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("changes.workspace.canonicalMatch")}</p>
              <p className="mt-2 text-sm text-[#596270]">{canonicalDisplayLabel(editContext, selected)}</p>
            </div>
          </div>
          <div className="mt-4">{canonicalBody}</div>
        </Card>
      )}

      {compact ? (
        <CompactSection
          title={translate("changes.workspace.technicalDetails")}
          summary={translate("changes.workspace.technicalCompactSummary")}
          open={expandedSections.extras}
          onToggle={() => setExpandedSections((current) => ({ ...current, extras: !current.extras }))}
        >
          <div className="flex flex-wrap gap-2">
            <Button asChild size="sm" variant="ghost">
              <Link href={withBasePath(basePath, `/changes/${selected.id}/canonical`)}>
                <SquarePen className="mr-2 h-4 w-4" />
                {translate("changes.editThenApprove")}
              </Link>
            </Button>
            {selected.change_type !== "removed" ? (
              <Button asChild size="sm" variant="ghost">
                <Link href={withBasePath(basePath, `/changes/${selected.id}/proposal`)}>
                  <PencilLine className="mr-2 h-4 w-4" />
                  {translate("changeEdit.proposalEdit")}
                </Link>
              </Button>
            ) : null}
          </div>
        </CompactSection>
      ) : null}
    </div>
  );
}

function DecisionWorkspaceRail({
  selected,
  labelLearning,
  labelLearningBusy,
  labelLearningError,
  learningOpen,
  newFamilyLabel,
  editContext,
  decisionBusy,
  onMarkViewed,
  onDecide,
  onLearningToggle,
  onApproveAndLearnExisting,
  onApproveAndLearnCreate,
  onNewFamilyLabelChange,
  onRetryLearningContext,
  basePath = "",
  compact = false,
}: Pick<
  DecisionWorkspaceProps,
  | "selected"
  | "labelLearning"
  | "labelLearningBusy"
  | "labelLearningError"
  | "learningOpen"
  | "newFamilyLabel"
  | "editContext"
  | "decisionBusy"
  | "onMarkViewed"
  | "onDecide"
  | "onLearningToggle"
  | "onApproveAndLearnExisting"
  | "onApproveAndLearnCreate"
  | "onNewFamilyLabelChange"
  | "onRetryLearningContext"
  | "basePath"
  | "compact"
>) {
  const pending = selected.review_status === "pending";
  const decisionSupport = selected.decision_support;
  const learningAvailable = pending && labelLearning?.status === "unresolved";
  const mappingFamily =
    labelLearning?.resolved_canonical_label ||
    (labelLearning?.status === "resolved" ? canonicalDisplayLabel(editContext, selected) : null);
  const mappingLine = labelLearning
    ? translate("changes.mapping.contextLine", {
        course: labelLearning.course_display || translate("common.labels.unknown"),
        label: labelLearning.raw_label || translate("common.labels.unknown"),
        ordinal: labelLearning.ordinal ?? "N/A",
      })
    : null;

  return (
    <div className="space-y-4">
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("changes.workspace.decision")}</p>
            <p className="mt-2 text-sm text-[#596270]">
              {pending ? translate("changes.needsDecision") : translate("changes.reviewed")}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {decisionSupport ? (
              <>
                <Badge tone={suggestedActionTone(decisionSupport.suggested_action)}>
                  {suggestedActionLabel(decisionSupport.suggested_action)}
                </Badge>
                <Badge tone={riskTone(decisionSupport.risk_level)}>{formatStatusLabel(decisionSupport.risk_level)}</Badge>
              </>
            ) : null}
          </div>
        </div>

        <div className="mt-4 space-y-3">
          <div
            className={`rounded-[1.15rem] border p-3 ${
              decisionSupport?.suggested_action === "approve" ? "border-[rgba(31,94,255,0.24)] bg-[rgba(31,94,255,0.06)]" : "border-line/80 bg-white/72"
            }`}
          >
            <Button className="w-full" onClick={() => onDecide("approve")} disabled={!pending || decisionBusy !== null}>
              <CheckCheck className="mr-2 h-4 w-4" />
              {decisionBusy === "approve" ? translate("changes.approving") : translate("changes.approve")}
            </Button>
            <p className="mt-2 text-xs leading-5 text-[#596270]">{actionPreviewText(selected, "approve")}</p>
          </div>
          <div
            className={`rounded-[1.15rem] border p-3 ${
              decisionSupport?.suggested_action === "reject" ? "border-[rgba(215,90,45,0.24)] bg-[#fff4ee]" : "border-line/80 bg-white/72"
            }`}
          >
            <Button className="w-full" variant="danger" onClick={() => onDecide("reject")} disabled={!pending || decisionBusy !== null}>
              <XCircle className="mr-2 h-4 w-4" />
              {decisionBusy === "reject" ? translate("changes.rejecting") : translate("changes.reject")}
            </Button>
            <p className="mt-2 text-xs leading-5 text-[#596270]">{actionPreviewText(selected, "reject")}</p>
          </div>
          <div
            className={`rounded-[1.15rem] border p-3 ${
              decisionSupport?.suggested_action === "edit" ? "border-[rgba(215,162,45,0.26)] bg-[#fff8e8]" : "border-line/80 bg-white/72"
            }`}
          >
            <Button asChild className="w-full" variant="ghost">
              <Link href={withBasePath(basePath, `/changes/${selected.id}/canonical`)}>
                <SquarePen className="mr-2 h-4 w-4" />
                {translate("changes.editThenApprove")}
              </Link>
            </Button>
            <p className="mt-2 text-xs leading-5 text-[#596270]">{actionPreviewText(selected, "edit")}</p>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="ghost" onClick={onMarkViewed} disabled={Boolean(selected.viewed_at)}>
            <Eye className="mr-2 h-4 w-4" />
            {selected.viewed_at ? translate("changes.viewed") : translate("changes.markViewed")}
          </Button>
          <Button variant="ghost" onClick={onLearningToggle} disabled={!learningAvailable || labelLearningBusy === "preview"}>
            <Sparkles className="mr-2 h-4 w-4" />
            {translate("changes.approveAndLearn")}
          </Button>
          {selected.change_type !== "removed" ? (
            <Button asChild variant="ghost">
              <Link href={withBasePath(basePath, `/changes/${selected.id}/proposal`)}>
                <PencilLine className="mr-2 h-4 w-4" />
                {translate("changeEdit.proposalEdit")}
              </Link>
            </Button>
          ) : null}
        </div>

        {!pending ? (
          <div className="mt-4 rounded-[1.1rem] border border-line/80 bg-white/75 p-4 text-sm text-[#596270]">
            {translate("changes.alreadyReviewedState", {
              status: formatStatusLabel(selected.review_status).toLowerCase(),
            })}
          </div>
        ) : null}
      </Card>

      {pending && labelLearningBusy === "preview" ? (
        <Card className="p-5 text-sm text-[#596270]">
          <p className="font-medium text-ink">{translate("changes.approveAndLearn")}</p>
          <p className="mt-2 leading-6">{translate("changes.loading")}</p>
        </Card>
      ) : null}

      {pending && labelLearningError ? (
        <Card className="border-[#efc4b5] bg-[#fff3ef] p-5 text-sm text-[#7f3d2a]">
          <p className="font-medium text-ink">{translate("changes.approveAndLearn")}</p>
          <p className="mt-2 leading-6">{labelLearningError}</p>
          <div className="mt-3">
            <Button size="sm" variant="ghost" onClick={onRetryLearningContext}>
              {translate("changes.retryLearningContext")}
            </Button>
          </div>
        </Card>
      ) : null}

      {labelLearning ? (
        <Card className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("changes.mapping.title")}</p>
              {mappingLine ? <p className="mt-2 text-sm text-[#596270]">{mappingLine}</p> : null}
            </div>
            <Button asChild size="sm" variant="ghost">
              <Link href={withBasePath(basePath, "/families")}>{translate("changes.mapping.openFamilies")}</Link>
            </Button>
          </div>
          <div className="mt-4 grid gap-3">
            <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
              <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("changes.mapping.observedLabel")}</p>
              <p className="mt-2 text-sm font-medium text-ink">{labelLearning.raw_label || translate("common.labels.unknown")}</p>
            </div>
            <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
              <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("changes.mapping.currentFamily")}</p>
              <p className="mt-2 text-sm font-medium text-ink">{mappingFamily || translate("changes.mapping.unresolvedFamily")}</p>
            </div>
          </div>
          <p className="mt-4 text-sm leading-6 text-[#314051]">
            {labelLearning.status === "resolved"
              ? translate("changes.mapping.explanationResolved")
              : translate("changes.mapping.explanationUnresolved")}
          </p>
          {labelLearning.status === "resolved" ? (
            <p className="mt-3 text-sm leading-6 text-[#314051]">
              {translate("changes.mapping.alreadyResolvesTo", {
                label: labelLearning.resolved_canonical_label || canonicalDisplayLabel(editContext, selected),
              })}
            </p>
          ) : null}
          {learningAvailable ? (
            <div className="mt-4 space-y-4">
              {!learningOpen ? (
                <Button size="sm" variant="ghost" onClick={onLearningToggle}>
                  <Sparkles className="mr-2 h-4 w-4" />
                  {translate("changes.approveAndLearn")}
                </Button>
              ) : (
                <>
                  <div className="flex flex-wrap gap-2">
                    {labelLearning.families.map((family) => (
                      <Button
                        key={family.id}
                        size="sm"
                        variant="ghost"
                        disabled={labelLearningBusy === "apply"}
                        onClick={() => onApproveAndLearnExisting(family.id, labelLearning.raw_label || "label", family.canonical_label)}
                      >
                        {translate("changes.mapping.learnAs", { label: family.canonical_label })}
                      </Button>
                    ))}
                  </div>
                  <div className="flex flex-wrap gap-3">
                    <Input
                      className="max-w-sm"
                      value={newFamilyLabel}
                      onChange={(event) => onNewFamilyLabelChange(event.target.value)}
                      placeholder={translate("changes.newFamilyPlaceholder")}
                    />
                    <Button size="sm" disabled={labelLearningBusy === "apply" || !newFamilyLabel.trim()} onClick={onApproveAndLearnCreate}>
                      {translate("changes.createFamilyAndApprove")}
                    </Button>
                  </div>
                </>
              )}
            </div>
          ) : null}
        </Card>
      ) : null}

      <ChangeAgentCard changeId={selected.id} basePath={basePath} />

      <Card className="p-5">
        <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("changes.workspace.technicalDetails")}</p>
        <div className="mt-4 grid gap-3">
          <div className="rounded-[1rem] border border-line/80 bg-white/75 p-4 text-sm text-[#314051]">
            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("changes.workspace.reviewBucket")}</p>
            <p className="mt-2 font-medium text-ink">{formatStatusLabel(selected.review_bucket)}</p>
            <p className="mt-3 text-xs text-[#6d7885]">Intake phase: {formatStatusLabel(selected.intake_phase)}</p>
          </div>
          <div className="rounded-[1rem] border border-line/80 bg-white/75 p-4 text-sm text-[#314051]">
            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("changes.workspace.sourceReferences")}</p>
            <p className="mt-2 font-medium text-ink">
              {selected.primary_source ? sourceDescriptor(selected.primary_source) : translate("changes.noPrimarySource")}
            </p>
            <p className="mt-3 text-xs text-[#6d7885]">
              {selected.proposal_sources.length} proposal source{selected.proposal_sources.length === 1 ? "" : "s"} · {confidenceLabel(selected)}
            </p>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button asChild size="sm" variant="ghost">
            <Link href={withBasePath(basePath, `/changes/${selected.id}/canonical`)}>
              <SquarePen className="mr-2 h-4 w-4" />
              {translate("changes.editThenApprove")}
            </Link>
          </Button>
          {selected.change_type !== "removed" ? (
            <Button asChild size="sm" variant="ghost">
              <Link href={withBasePath(basePath, `/changes/${selected.id}/proposal`)}>
                <PencilLine className="mr-2 h-4 w-4" />
                {translate("changeEdit.proposalEdit")}
              </Link>
            </Button>
          ) : null}
        </div>
      </Card>
    </div>
  );
}

function DecisionWorkspace(props: DecisionWorkspaceProps) {
  return (
    <div className="space-y-4">
      <DecisionWorkspaceMain {...props} />
      <DecisionWorkspaceRail {...props} />
    </div>
  );
}

function DecisionWorkspacePlaceholder({
  reviewBucket,
  initialReviewComplete,
  basePath = "",
}: {
  reviewBucket: "changes" | "initial_review";
  initialReviewComplete: boolean;
  basePath?: string;
}) {
  if (reviewBucket === "initial_review" && initialReviewComplete) {
    return (
      <Card className="animate-surface-enter p-6">
        <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("changes.initialReview")}</p>
        <h3 className="mt-2 text-xl font-semibold text-ink">{translate("changes.empty.initialCompleteTitle")}</h3>
        <p className="mt-3 text-sm leading-6 text-[#596270]">{translate("changes.empty.initialCompleteDescription")}</p>
        <div className="mt-5">
          <Button asChild size="sm">
            <Link href={withBasePath(basePath, "/changes")}>{translate("changes.openReplayReview")}</Link>
          </Button>
        </div>
      </Card>
    );
  }

  return <Card className="animate-surface-enter p-6 text-sm text-[#596270]">{translate("changes.selectChange")}</Card>;
}

export function ChangeItemsPanel({
  basePath = "",
  reviewBucket = "changes",
}: {
  basePath?: string;
  reviewBucket?: "changes" | "initial_review";
}) {
  const [statusFilter, setStatusFilter] = useState<(typeof statusOptions)[number]>("pending");
  const [sourceFilter, setSourceFilter] = useState<string>("all");
  const [selectedChangeId, setSelectedChangeId] = useState<number | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [evidenceView, setEvidenceView] = useState<EvidenceViewMode>("summary");
  const [evidence, setEvidence] = useState<LoadedEvidence | null>(null);
  const [previewBusy, setPreviewBusy] = useState<"before" | "after" | null>(null);
  const [currentEvidenceSide, setCurrentEvidenceSide] = useState<"before" | "after">("after");
  const [decisionBusy, setDecisionBusy] = useState<"approve" | "reject" | null>(null);
  const [batchBusy, setBatchBusy] = useState<"approve" | "reject" | null>(null);
  const [labelLearning, setLabelLearning] = useState<LabelLearningPreview | null>(null);
  const [labelLearningBusy, setLabelLearningBusy] = useState<"preview" | "apply" | null>(null);
  const [labelLearningError, setLabelLearningError] = useState<string | null>(null);
  const [labelLearningReloadNonce, setLabelLearningReloadNonce] = useState(0);
  const [learningOpen, setLearningOpen] = useState(false);
  const [newFamilyLabel, setNewFamilyLabel] = useState("");
  const [banner, setBanner] = useState<Banner>(null);
  const [requestedFocusId, setRequestedFocusId] = useState<number | null>(null);
  const [editContext, setEditContext] = useState<ChangeEditContext | null>(null);
  const [editContextBusy, setEditContextBusy] = useState(false);
  const [editContextError, setEditContextError] = useState<string | null>(null);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const { side: drawerSide, isDesktop, isMobile, showInlineWorkspace } = useWorkspaceLayout();
  const changeQuery: Parameters<typeof listChanges>[0] = {
    review_status: statusFilter,
    review_bucket: reviewBucket,
    intake_phase: reviewBucket === "initial_review" ? "baseline" : undefined,
    limit: 50,
    source_id: sourceFilter === "all" ? null : Number(sourceFilter),
  };
  const sources = useApiResource<SourceRow[]>(() => listSources({ status: "all" }), [], null, {
    cacheKey: sourceListCacheKey("all"),
  });
  const summary = useApiResource<ChangesWorkbenchSummary>(() => getChangesSummary(), [], null, {
    cacheKey: changesSummaryCacheKey(),
  });

  const { data, loading, error, refresh, setData } = useApiResource<ChangeItem[]>(
    () => listChanges(changeQuery),
    [reviewBucket, sourceFilter, statusFilter],
    null,
    { cacheKey: changesListCacheKey(changeQuery) },
  );
  const rows = useMemo(() => data || [], [data]);
  const groups = useMemo(() => groupChangesByCourse(rows), [rows]);
  const selected = rows.find((row) => row.id === selectedChangeId) || null;
  const selectedEvidenceAvailability = selected ? getEvidenceAvailability(selected) : { before: false, after: false };
  const selectedIdsSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const allVisibleSelected = rows.length > 0 && rows.every((row) => selectedIdsSet.has(row.id));

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const raw = new URLSearchParams(window.location.search).get("focus");
    setRequestedFocusId(raw ? Number(raw) : null);
  }, []);

  useEffect(() => {
    if (rows.length === 0) {
      setSelectedChangeId(null);
      setSelectedIds([]);
      setEvidence(null);
      setMobileDetailOpen(false);
      return;
    }

    setSelectedIds((prev) => prev.filter((id) => rows.some((row) => row.id === id)));

    const preferredRow =
      requestedFocusId && rows.some((row) => row.id === requestedFocusId)
        ? rows.find((row) => row.id === requestedFocusId) || rows[0]
        : rows[0];

    if (!selectedChangeId || !rows.some((row) => row.id === selectedChangeId)) {
      setSelectedChangeId(preferredRow.id);
      setCurrentEvidenceSide(defaultEvidenceSide(preferredRow));
      setEvidence(null);
      if (statusFilter !== "pending") {
        setLearningOpen(false);
      }
    }
  }, [requestedFocusId, rows, selectedChangeId, statusFilter]);

  const markViewed = useCallback(
    async (change: ChangeItem) => {
      if (change.viewed_at) {
        return;
      }
      try {
        const updated = await markChangeViewed(change.id, { viewed: true, note: "ui_opened" });
        setData((prev: ChangeItem[] | null) => prev?.map((row: ChangeItem) => (row.id === updated.id ? updated : row)) || prev);
      } catch {
        // Non-fatal.
      }
    },
    [setData],
  );

  const openEvidence = useCallback(
    async (change: ChangeItem, side: "before" | "after") => {
      setPreviewBusy(side);
      setCurrentEvidenceSide(side);
      await markViewed(change);
      const availability = getEvidenceAvailability(change);
      if (!availability[side]) {
        const message =
          side === "after"
            ? "No frozen after evidence is available for this change."
            : "No frozen before evidence is available for this change.";
        setEvidence({
          payload: {
            side,
            content_type: "text/plain",
            truncated: false,
            filename: `change-${change.id}-${side}.txt`,
            provider: null,
            structured_kind: "generic",
            structured_items: [],
            event_count: 0,
            events: [],
            preview_text: message,
          },
          summaryFallback: message,
        });
        setPreviewBusy(null);
        return;
      }
      try {
        const payload = await previewChangeEvidence(change.id, side);
        const fallback =
          payload.events
            ?.map((event) => [event.summary || "(untitled)", event.dtstart, event.location].filter(Boolean).join(" · "))
            .join("\n") || "No preview text available.";
        setEvidence({ payload, summaryFallback: fallback });
      } catch (err) {
        const message = err instanceof Error ? err.message : "Unable to load evidence preview.";
        setEvidence({
          payload: {
            side,
            content_type: "text/plain",
            truncated: false,
            filename: `change-${change.id}-${side}.txt`,
            provider: null,
            structured_kind: "generic",
            structured_items: [],
            event_count: 0,
            events: [],
            preview_text: message,
          },
          summaryFallback: message,
        });
      } finally {
        setPreviewBusy(null);
      }
    },
    [markViewed],
  );

  useEffect(() => {
    if (!selected) {
      setEvidence(null);
      setEditContext(null);
      setEditContextError(null);
      setEditContextBusy(false);
      return;
    }

    const preferredSide = getEvidenceAvailability(selected)[currentEvidenceSide] ? currentEvidenceSide : defaultEvidenceSide(selected);
    if (preferredSide !== currentEvidenceSide) {
      setCurrentEvidenceSide(preferredSide);
      return;
    }

    void openEvidence(selected, currentEvidenceSide);
  }, [currentEvidenceSide, openEvidence, selected]);

  useEffect(() => {
    if (!selected) {
      setEditContext(null);
      setEditContextError(null);
      setEditContextBusy(false);
      return;
    }

    let cancelled = false;
    setEditContextBusy(true);
    setEditContext(null);
    setEditContextError(null);

    void getChangeEditContext(selected.id)
      .then((payload) => {
        if (!cancelled) {
          setEditContext(payload);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setEditContextError(err instanceof Error ? err.message : "Unable to load canonical match context.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setEditContextBusy(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [selected]);

  useEffect(() => {
    if (!selected || selected.review_status !== "pending") {
      setLabelLearning(null);
      setLabelLearningBusy(null);
      setLabelLearningError(null);
      setLearningOpen(false);
      setNewFamilyLabel("");
      return;
    }

    let cancelled = false;
    setLabelLearningBusy("preview");
    setLabelLearning(null);
    setLabelLearningError(null);

    void previewChangeLabelLearning(selected.id)
      .then((payload) => {
        if (cancelled) return;
        setLabelLearning(payload);
        setNewFamilyLabel(payload.raw_label || "");
      })
      .catch((err) => {
        if (cancelled) return;
        setLabelLearning(null);
        setLabelLearningError(err instanceof Error ? err.message : "Unable to load label learning context.");
        setNewFamilyLabel("");
      })
      .finally(() => {
        if (!cancelled) {
          setLabelLearningBusy((current) => (current === "preview" ? null : current));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [labelLearningReloadNonce, selected]);

  async function decide(decision: "approve" | "reject") {
    if (!selected) return;
    setDecisionBusy(decision);
    setBanner(null);
    try {
      await decideChange(selected.id, { decision, note: `ui_${decision}` });
      setSelectedIds((prev) => prev.filter((id) => id !== selected.id));
      setBanner({ tone: "info", text: decision === "approve" ? "Change approved." : "Change rejected." });
      setLearningOpen(false);
      setMobileDetailOpen(false);
      await refresh();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Decision failed" });
    } finally {
      setDecisionBusy(null);
    }
  }

  async function decideBatch(decision: "approve" | "reject") {
    if (selectedIds.length === 0) return;
    setBatchBusy(decision);
    setBanner(null);
    try {
      const payload = await batchDecideChanges({ ids: selectedIds, decision, note: `ui_batch_${decision}` });
      setSelectedIds([]);
      setBanner({
        tone: payload.failed > 0 ? "error" : "info",
        text:
          payload.failed > 0
            ? `${payload.succeeded} updated, ${payload.failed} skipped.`
            : decision === "approve"
              ? `${payload.succeeded} changes approved.`
              : `${payload.succeeded} changes rejected.`,
      });
      await refresh();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Batch decision failed" });
    } finally {
      setBatchBusy(null);
    }
  }

  async function approveAndLearn(payload: { mode: "add_alias" | "create_family"; family_id?: number; canonical_label?: string; successText: string }) {
    if (!selected) return;
    setLabelLearningBusy("apply");
    setBanner(null);
    try {
      await applyChangeLabelLearning(selected.id, {
        mode: payload.mode,
        family_id: payload.family_id ?? null,
        canonical_label: payload.canonical_label ?? null,
      });
      setSelectedIds((prev) => prev.filter((id) => id !== selected.id));
      setLearningOpen(false);
      setMobileDetailOpen(false);
      setBanner({ tone: "info", text: payload.successText });
      await refresh();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("changes.banners.learningFailed") });
    } finally {
      setLabelLearningBusy(null);
    }
  }

  function toggleRowSelection(changeId: number, checked: boolean) {
    setSelectedIds((prev) => {
      if (checked) {
        if (prev.includes(changeId)) return prev;
        return [...prev, changeId];
      }
      return prev.filter((id) => id !== changeId);
    });
  }

  function toggleVisibleSelection(checked: boolean) {
    if (!checked) {
      setSelectedIds((prev) => prev.filter((id) => !rows.some((row) => row.id === id)));
      return;
    }
    setSelectedIds((prev) => {
      const next = new Set(prev);
      for (const row of rows) next.add(row.id);
      return Array.from(next);
    });
  }

  function openChange(changeId: number) {
    setSelectedChangeId(changeId);
    setCurrentEvidenceSide("after");
    if (isMobile) {
      setMobileDetailOpen(true);
    }
  }

  if (loading || summary.loading) return <WorkbenchLoadingShell variant="changes" />;
  if (error) return <ReviewInboxError message={error} basePath={basePath} />;
  if (summary.error) return <ErrorState message={`${translate("changes.banners.changesSummaryFailed")} ${summary.error}`} />;
  if (!summary.data) return <ErrorState message={translate("changes.banners.changesSummaryUnavailable")} />;

  const summaryData = summary.data;
  const initialReviewProgress = summaryData.workspace_posture.initial_review;
  const initialReviewComplete = reviewBucket === "initial_review" && initialReviewProgress.pending_count === 0;

  return (
    <div className="space-y-5">
      <Card className="animate-surface-enter p-5 md:p-6">
        <div className="space-y-5">
          <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
            <div className="max-w-3xl">
              <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">{reviewBucket === "initial_review" ? translate("changes.initialReview") : translate("changes.replayReview")}</p>
              <h3 className="mt-2 text-2xl font-semibold text-ink">
                {reviewBucket === "initial_review"
                  ? initialReviewComplete
                    ? translate("changes.hero.initialReviewCompleteTitle")
                    : translate("changes.hero.initialReviewPendingTitle")
                  : translate("changes.hero.replayTitle")}
              </h3>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                {reviewBucket === "initial_review"
                  ? initialReviewComplete
                    ? translate("changes.hero.initialReviewCompleteSummary")
                    : translate("changes.hero.initialReviewPendingSummary")
                  : translate("changes.hero.replaySummary")}
              </p>
              {reviewBucket === "initial_review" ? (
                <div className="mt-4 max-w-xl space-y-3 rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
                  <div className="flex flex-wrap gap-2 text-sm">
                    <Badge tone={initialReviewComplete ? "approved" : "pending"}>
                      {translate("changes.hero.pending", { count: initialReviewProgress.pending_count })}
                    </Badge>
                    <Badge tone="info">{translate("changes.hero.reviewed", { count: initialReviewProgress.reviewed_count })}</Badge>
                    <Badge tone="info">{translate("changes.hero.total", { count: initialReviewProgress.total_count })}</Badge>
                  </div>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between gap-3 text-sm text-[#596270]">
                      <span>
                        {initialReviewComplete
                          ? initialReviewProgress.completed_at
                            ? translate("changes.hero.completedAt", { time: formatDateTime(initialReviewProgress.completed_at) })
                            : translate("changes.hero.completed")
                          : translate("changes.hero.reviewedOfTotal", {
                              reviewed: initialReviewProgress.reviewed_count,
                              total: initialReviewProgress.total_count,
                            })}
                      </span>
                      <span>{initialReviewProgress.completion_percent}%</span>
                    </div>
                    <div className="h-2 rounded-full bg-white/60">
                      <div
                        className="h-2 rounded-full bg-cobalt transition-all duration-500"
                        style={{ width: `${Math.min(Math.max(initialReviewProgress.completion_percent, 0), 100)}%` }}
                      />
                    </div>
                  </div>
                  {initialReviewComplete ? (
                    <div>
                      <Button asChild size="sm">
                        <Link href={withBasePath(basePath, "/changes")}>{translate("changes.openReplayReview")}</Link>
                      </Button>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
            <div className="w-full xl:w-auto">
              <div className="hidden w-max flex-wrap gap-2 md:flex xl:justify-end">
                {statusOptions.map((status) => (
                  <Button key={status} variant={statusFilter === status ? "primary" : "ghost"} size="sm" onClick={() => setStatusFilter(status)}>
                    {formatStatusLabel(status)}
                  </Button>
                ))}
              </div>
              <div className="md:hidden">
                <Button size="sm" variant="ghost" onClick={() => setMobileFiltersOpen(true)}>
                  {translate("changes.filters")}
                </Button>
              </div>
            </div>
          </div>

          {banner ? (
            <Card className={banner.tone === "error" ? "border-[#efc4b5] bg-[#fff3ef] p-4" : "border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] p-4"}>
              <p className="text-sm text-[#314051]">{banner.text}</p>
            </Card>
          ) : null}

          {reviewBucket === "changes" && summaryData.baseline_review_pending > 0 ? (
            <div className="rounded-[1.15rem] border border-[rgba(215,90,45,0.18)] bg-[#fff8f4] p-4">
              <p className="text-sm font-medium text-ink">
                {summaryData.baseline_review_pending === 1
                  ? translate("changes.baselineWaitingOne")
                  : translate("changes.baselineWaitingMany", { count: summaryData.baseline_review_pending })}
              </p>
              <p className="mt-2 text-sm text-[#596270]">
                {translate("changes.empty.baselineWaitingDescription")}
              </p>
              <div className="mt-4">
                <Button asChild size="sm">
                  <Link href={withBasePath(basePath, "/changes?bucket=initial_review")}>{translate("changes.openInitialReviewShort")}</Link>
                </Button>
              </div>
            </div>
          ) : null}

          <div className="flex flex-col gap-3 text-sm text-[#596270] lg:flex-row lg:flex-wrap lg:items-center lg:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="info">{reviewBucket === "initial_review" ? translate("changes.initialReviewLane") : translate("changes.laneBadge", { status: formatStatusLabel(statusFilter) })}</Badge>
              <Badge tone="info">{translate("changes.visibleChanges", { count: rows.length })}</Badge>
              <Badge tone="info">{translate("changes.courseGroups", { count: groups.length })}</Badge>
            </div>
            <label className="hidden items-center gap-2 rounded-full border border-line/80 bg-white/75 px-3 py-1.5 text-sm text-[#314051] md:flex">
              <span className="text-[#6d7885]">{translate("changes.source")}</span>
              <select
                aria-label={translate("changes.source")}
                className="bg-transparent outline-none"
                value={sourceFilter}
                onChange={(event) => setSourceFilter(event.target.value)}
              >
                <option value="all">{formatStatusLabel("all")}</option>
                {(sources.data || []).map((source) => (
                  <option key={source.source_id} value={String(source.source_id)}>
                    {source.display_name || source.provider || `Source ${source.source_id}`}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
      </Card>

      <div
        className={`grid gap-5 ${
          isMobile
            ? ""
            : isDesktop
              ? "xl:grid-cols-[minmax(300px,0.64fr)_minmax(0,1.36fr)]"
              : "grid-cols-[minmax(280px,0.72fr)_minmax(0,1.28fr)]"
        }`}
      >
        <Card className="self-start p-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("changes.inboxEyebrow")}</p>
              <h2 className="mt-1 text-lg font-semibold text-ink">{translate("changes.inboxTitle")}</h2>
            </div>
            {statusFilter === "pending" ? <Badge tone="pending">{translate("changes.selectedCount", { count: selectedIds.length })}</Badge> : <Badge tone="info">{translate("changes.rowsCount", { count: rows.length })}</Badge>}
          </div>

      {statusFilter === "pending" && isDesktop ? (
            <div className="mt-4 flex flex-wrap items-center justify-between gap-4 rounded-[1.15rem] border border-line/80 bg-white/65 p-4">
              <label className="flex items-center gap-3 text-sm text-[#314051]">
                <Checkbox aria-label="Select all visible review changes" checked={allVisibleSelected} onChange={(event) => toggleVisibleSelection(event.currentTarget.checked)} />
                {translate("changes.selectVisible")}
              </label>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="ghost" disabled={selectedIds.length === 0 || batchBusy === "reject"} onClick={() => void decideBatch("reject")}>
                  <XCircle className="mr-2 h-4 w-4" />
                  {batchBusy === "reject" ? translate("changes.rejecting") : translate("changes.rejectSelected")}
                </Button>
                <Button size="sm" disabled={selectedIds.length === 0 || batchBusy === "approve"} onClick={() => void decideBatch("approve")}>
                  <CheckCheck className="mr-2 h-4 w-4" />
                  {batchBusy === "approve" ? translate("changes.approving") : translate("changes.approveSelected")}
                </Button>
              </div>
            </div>
          ) : null}

          <div className="mt-5 space-y-5">
            {rows.length === 0 ? (
              <EmptyState
                title={
                  reviewBucket === "initial_review"
                    ? initialReviewComplete
                      ? translate("changes.empty.initialCompleteTitle")
                      : translate("changes.empty.initialLaneEmptyTitle")
                    : translate("changes.empty.replayLaneEmptyTitle")
                }
                description={
                  reviewBucket === "initial_review"
                    ? initialReviewComplete
                      ? translate("changes.empty.initialCompleteDescription")
                      : translate("changes.empty.initialLaneEmptyDescription")
                    : translate("changes.empty.replayLaneEmptyDescription")
                }
              />
            ) : (
              groups.map((group) => (
                <div key={group.course} className="space-y-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("changes.course")}</p>
                      <h3 className="mt-1 text-sm font-semibold text-ink">{group.course}</h3>
                    </div>
                    <Badge tone="info">{translate("changes.courseChanges", { count: group.changes.length })}</Badge>
                  </div>
                  <div className="space-y-3">
                    {group.changes.map((row) => (
                      <ChangeInboxRow
                        key={row.id}
                        row={row}
                        selected={selectedChangeId === row.id}
                        checked={selectedIdsSet.has(row.id)}
                        onToggleSelection={(checked) => toggleRowSelection(row.id, checked)}
                        onOpen={() => openChange(row.id)}
                        showSelection={isDesktop && statusFilter === "pending"}
                        compact={!isDesktop}
                        basePath={basePath}
                      />
                    ))}
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>

        <div className={showInlineWorkspace ? "block" : "hidden"}>
          {selected ? (
            isDesktop ? (
              <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_280px]">
                <DecisionWorkspaceMain
                  selected={selected}
                  currentEvidenceSide={currentEvidenceSide}
                  evidenceView={evidenceView}
                  evidence={evidence}
                  previewBusy={previewBusy}
                  editContext={editContext}
                  editContextBusy={editContextBusy}
                  editContextError={editContextError}
                  onEvidenceSideChange={(side) => void openEvidence(selected, side)}
                  onEvidenceViewChange={setEvidenceView}
                  basePath={basePath}
                  compact={false}
                />
                <div className="self-start xl:sticky xl:top-24">
                  <DecisionWorkspaceRail
                    selected={selected}
                    labelLearning={labelLearning}
                    labelLearningBusy={labelLearningBusy}
                    labelLearningError={labelLearningError}
                    learningOpen={learningOpen}
                    newFamilyLabel={newFamilyLabel}
                    editContext={editContext}
                    decisionBusy={decisionBusy}
                    onMarkViewed={() => void markViewed(selected)}
                    onDecide={(decision) => void decide(decision)}
                    onLearningToggle={() => setLearningOpen((current) => !current)}
                    onApproveAndLearnExisting={(familyId, rawLabel, canonicalLabel) =>
                      void approveAndLearn({
                        mode: "add_alias",
                        family_id: familyId,
                        successText: translate("changes.learnedExisting", { rawLabel, canonicalLabel }),
                      })
                    }
                    onApproveAndLearnCreate={() =>
                      void approveAndLearn({
                        mode: "create_family",
                        canonical_label: newFamilyLabel.trim(),
                        successText: translate("changes.learnedCreated", { label: newFamilyLabel.trim() }),
                      })
                    }
                    onNewFamilyLabelChange={setNewFamilyLabel}
                    onRetryLearningContext={() => setLabelLearningReloadNonce((current) => current + 1)}
                    basePath={basePath}
                  />
                </div>
              </div>
            ) : (
              <DecisionWorkspace
                selected={selected}
                currentEvidenceSide={currentEvidenceSide}
                evidenceView={evidenceView}
                evidence={evidence}
                previewBusy={previewBusy}
                labelLearning={labelLearning}
                labelLearningBusy={labelLearningBusy}
                labelLearningError={labelLearningError}
                learningOpen={learningOpen}
                newFamilyLabel={newFamilyLabel}
                editContext={editContext}
                editContextBusy={editContextBusy}
                editContextError={editContextError}
                decisionBusy={decisionBusy}
                onMarkViewed={() => void markViewed(selected)}
                onEvidenceSideChange={(side) => void openEvidence(selected, side)}
                onEvidenceViewChange={setEvidenceView}
                onDecide={(decision) => void decide(decision)}
                onLearningToggle={() => setLearningOpen((current) => !current)}
                onApproveAndLearnExisting={(familyId, rawLabel, canonicalLabel) =>
                  void approveAndLearn({
                    mode: "add_alias",
                    family_id: familyId,
                    successText: translate("changes.learnedExisting", { rawLabel, canonicalLabel }),
                  })
                }
                onApproveAndLearnCreate={() =>
                  void approveAndLearn({
                    mode: "create_family",
                    canonical_label: newFamilyLabel.trim(),
                    successText: translate("changes.learnedCreated", { label: newFamilyLabel.trim() }),
                  })
                }
                onNewFamilyLabelChange={setNewFamilyLabel}
                onRetryLearningContext={() => setLabelLearningReloadNonce((current) => current + 1)}
                basePath={basePath}
                compact
              />
            )
          ) : (
            <DecisionWorkspacePlaceholder reviewBucket={reviewBucket} initialReviewComplete={initialReviewComplete} basePath={basePath} />
          )}
        </div>
      </div>

      {isMobile ? (
        <Sheet
          open={mobileDetailOpen && selected !== null}
          onOpenChange={(open) => {
            setMobileDetailOpen(open);
          }}
        >
          <SheetContent side={drawerSide} className="overflow-y-auto">
            {selected ? (
              <>
                <SheetHeader>
                  <div>
                    <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">{translate("changes.workspace.title")}</p>
                    <SheetTitle className="mt-3 leading-tight">{summarizeChange(selected).title}</SheetTitle>
                    <SheetDescription>{translate("changes.focusedSections")}</SheetDescription>
                  </div>
                  <div className="flex items-center gap-3">
                    <SheetDismissButton />
                  </div>
                </SheetHeader>

                <div className="mt-6">
                  <DecisionWorkspace
                    selected={selected}
                    currentEvidenceSide={currentEvidenceSide}
                    evidenceView={evidenceView}
                    evidence={evidence}
                    previewBusy={previewBusy}
                    labelLearning={labelLearning}
                    labelLearningBusy={labelLearningBusy}
                    labelLearningError={labelLearningError}
                    learningOpen={learningOpen}
                    newFamilyLabel={newFamilyLabel}
                    editContext={editContext}
                    editContextBusy={editContextBusy}
                    editContextError={editContextError}
                    decisionBusy={decisionBusy}
                    onMarkViewed={() => void markViewed(selected)}
                    onEvidenceSideChange={(side) => void openEvidence(selected, side)}
                    onEvidenceViewChange={setEvidenceView}
                    onDecide={(decision) => void decide(decision)}
                    onLearningToggle={() => setLearningOpen((current) => !current)}
                    onApproveAndLearnExisting={(familyId, rawLabel, canonicalLabel) =>
                      void approveAndLearn({
                        mode: "add_alias",
                        family_id: familyId,
                        successText: translate("changes.learnedExisting", { rawLabel, canonicalLabel }),
                      })
                    }
                    onApproveAndLearnCreate={() =>
                      void approveAndLearn({
                        mode: "create_family",
                        canonical_label: newFamilyLabel.trim(),
                        successText: translate("changes.learnedCreated", { label: newFamilyLabel.trim() }),
                      })
                    }
                    onNewFamilyLabelChange={setNewFamilyLabel}
                    onRetryLearningContext={() => setLabelLearningReloadNonce((current) => current + 1)}
                    basePath={basePath}
                    compact
                  />
                </div>
              </>
            ) : null}
          </SheetContent>
        </Sheet>
      ) : null}

      <Sheet open={mobileFiltersOpen} onOpenChange={setMobileFiltersOpen}>
        <SheetContent side="bottom" className="overflow-y-auto md:hidden">
          <SheetHeader>
            <div>
              <SheetTitle>{translate("changes.reviewFiltersTitle")}</SheetTitle>
              <SheetDescription>{translate("changes.reviewFiltersSummary")}</SheetDescription>
            </div>
            <SheetDismissButton />
          </SheetHeader>
          <div className="mt-6 space-y-5">
            <div className="space-y-3">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("changes.status")}</p>
              <div className="flex flex-wrap gap-2">
                {statusOptions.map((status) => (
                  <Button
                    key={status}
                    variant={statusFilter === status ? "primary" : "ghost"}
                    size="sm"
                    onClick={() => setStatusFilter(status)}
                  >
                    {formatStatusLabel(status)}
                  </Button>
                ))}
              </div>
            </div>
            <div className="space-y-3">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("changes.source")}</p>
              <select
                aria-label={translate("changes.source")}
                className="h-11 w-full rounded-2xl border border-line bg-white/80 px-4 text-sm text-ink outline-none transition focus:border-cobalt focus:bg-white"
                value={sourceFilter}
                onChange={(event) => setSourceFilter(event.target.value)}
              >
                <option value="all">{formatStatusLabel("all")}</option>
                {(sources.data || []).map((source) => (
                  <option key={source.source_id} value={String(source.source_id)}>
                    {source.display_name || source.provider || `Source ${source.source_id}`}
                  </option>
                ))}
              </select>
            </div>
            <div className="rounded-[1rem] border border-line/80 bg-white/72 p-4 text-sm text-[#596270]">
              {rows.length} visible changes · {groups.length} course group{groups.length === 1 ? "" : "s"}
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
