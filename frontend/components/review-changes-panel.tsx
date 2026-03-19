"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CalendarRange, CheckCheck, ChevronDown, ChevronUp, Eye, FileSearch, PencilLine, Sparkles, SquarePen, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { Sheet, SheetContent, SheetDescription, SheetDismissButton, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import {
  applyLabelLearning,
  batchDecideReviewChanges,
  decideReviewChange,
  getReviewChangeEditContext,
  listReviewChanges,
  markReviewChangeViewed,
  previewLabelLearning,
  previewReviewChangeEvidence,
} from "@/lib/api/review";
import { withBasePath } from "@/lib/demo-mode";
import {
  formatDateTime,
  formatSemanticDue,
  formatStatusLabel,
  sourceDescriptor,
  sourceKindDescriptor,
  summarizeChange,
} from "@/lib/presenters";
import type { EvidencePreviewResponse, LabelLearningPreview, ReviewChange, ReviewEditContext } from "@/lib/types";
import { useApiResource } from "@/lib/use-api-resource";

const statusOptions = ["pending", "approved", "rejected"] as const;

type Banner = {
  tone: "info" | "error";
  text: string;
} | null;

type ChangeSummarySide = NonNullable<ReviewChange["change_summary"]>["old"];
type EvidenceViewMode = "summary" | "raw";
type CompactWorkspaceSection = "evidence" | "match" | "extras";

type LoadedEvidence = {
  payload: EvidencePreviewResponse;
  summaryFallback: string;
};

type StructuredEvidenceItem = EvidencePreviewResponse["structured_items"][number];

function groupChangesByCourse(rows: ReviewChange[]) {
  const groups = new Map<string, ReviewChange[]>();
  for (const row of rows) {
    const course = row.after_event?.event_display.course_display || row.before_event?.event_display.course_display || "Unknown course";
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
      actionLabel={showSourcesCta ? "Open Sources" : undefined}
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
    return <p className="text-sm text-[#596270]">Structured preview unavailable. Switch to Raw to inspect the original evidence.</p>;
  }

  if (evidence.payload.structured_kind === "gmail_event") {
    return (
      <div className="space-y-3">
        {structuredItems.map((item, index) => (
          <div key={`${item.uid || "gmail"}-${index}`} className="rounded-[1.15rem] border border-line/80 bg-white/75 p-4 text-sm text-[#314051]">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-medium text-ink">{item.event_display?.display_label || "Untitled event"}</p>
                  {item.source_title ? <Badge tone="info">{item.source_title}</Badge> : null}
                </div>
                {item.uid ? <p className="mt-1 text-xs text-[#6d7885]">UID: {item.uid}</p> : null}
              </div>
              <Badge tone="approved">Email-backed</Badge>
            </div>
            <div className="mt-4 grid gap-2 md:grid-cols-2">
              <p>Due: {formatDateTime(item.start_at, "N/A")}</p>
              <p>Ends: {formatDateTime(item.end_at, "N/A")}</p>
              <EvidenceField label="Sender" value={item.sender} />
              <p>Received: {formatDateTime(item.internal_date, "Unknown")}</p>
              <EvidenceField label="Thread" value={item.thread_id} />
            </div>
            {item.snippet ? (
              <div className="mt-4 rounded-[1rem] border border-line/70 bg-white/80 p-3">
                <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">Mail summary</p>
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
                <p className="font-medium text-ink">{item.event_display?.display_label || "Untitled event"}</p>
                {item.source_title ? <Badge tone="info">{item.source_title}</Badge> : null}
              </div>
              {item.uid ? <p className="mt-1 text-xs text-[#6d7885]">UID: {item.uid}</p> : null}
            </div>
            <Badge tone="info">Event {index + 1}</Badge>
          </div>
          <div className="mt-4 grid gap-2 md:grid-cols-2">
            <p>Start: {formatDateTime(item.start_at, "N/A")}</p>
            <p>End: {formatDateTime(item.end_at, "N/A")}</p>
            <EvidenceField label="Location" value={item.location} />
            {item.url ? (
              <p className="truncate">
                <span className="text-[#6d7885]">Link:</span>{" "}
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
  const [layout, setLayout] = useState<{ side: "right" | "bottom"; isDesktop: boolean }>({
    side: "right",
    isDesktop: false,
  });

  useEffect(() => {
    function update() {
      setLayout({
        side: window.innerWidth < 1024 ? "bottom" : "right",
        isDesktop: window.innerWidth >= 1280,
      });
    }

    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  return layout;
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

function confidenceLabel(row: ReviewChange) {
  const value = row.proposal_sources.reduce<number | null>((highest, source) => {
    if (typeof source.confidence !== "number") {
      return highest;
    }
    return highest === null ? source.confidence : Math.max(highest, source.confidence);
  }, null);

  if (value === null) {
    return "Needs review";
  }

  return `Confidence ${Math.round(value * 100)}%`;
}

function canonicalDisplayLabel(context: ReviewEditContext | null, row: ReviewChange) {
  if (context?.editable_event?.family_name) {
    return context.editable_event.family_name;
  }
  return row.after_event?.event_display.family_name || row.before_event?.event_display.family_name || "No canonical family yet";
}

function canonicalTimelineLabel(context: ReviewEditContext | null) {
  if (!context) {
    return null;
  }

  const { editable_event: event } = context;
  const parts = [event.event_name || event.raw_type || null, formatSemanticDue(event as unknown as Record<string, unknown>, ""), event.raw_type || null]
    .filter((value, index, array) => Boolean(value) && array.indexOf(value) === index)
    .join(" · ");

  return parts || null;
}

function CompactSection({
  title,
  open,
  onToggle,
  children,
}: {
  title: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <Card className="animate-surface-enter overflow-hidden p-0">
      <button type="button" onClick={onToggle} className="flex w-full items-center justify-between gap-4 px-4 py-4 text-left">
        <p className="text-sm font-medium text-ink">{title}</p>
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
  row: ReviewChange;
  selected: boolean;
  checked: boolean;
  onToggleSelection: (checked: boolean) => void;
  onOpen: () => void;
  showSelection: boolean;
  compact: boolean;
  basePath?: string;
}) {
  const summary = summarizeChange(row);
  const beforeDue = formatSemanticDue((row.before_event || {}) as Record<string, unknown>, "No previous time");
  const afterDue = formatSemanticDue((row.after_event || {}) as Record<string, unknown>, "No new time");
  const primarySource = row.primary_source ? sourceDescriptor(row.primary_source) : row.proposal_sources[0] ? sourceDescriptor(row.proposal_sources[0]) : "Needs source confirmation";

  return (
    <div
      className={`animate-surface-enter interactive-lift rounded-[1.15rem] border p-4 transition-all duration-300 ${
        selected ? "border-[rgba(31,94,255,0.3)] bg-white shadow-[0_16px_32px_rgba(20,32,44,0.08)]" : "border-line/80 bg-white/72 hover:bg-white"
      }`}
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
                  <span>{row.viewed_at ? `Viewed ${formatDateTime(row.viewed_at)}` : "New in inbox"}</span>
                </>
              ) : (
                <>
                  <span>•</span>
                  <span>{row.review_status === "pending" ? "Needs decision" : "Reviewed"}</span>
                </>
              )}
            </div>
          </button>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button size="sm" variant={selected ? "secondary" : "soft"} onClick={onOpen}>
              <Eye className="mr-2 h-4 w-4" />
              {selected ? "Decision open" : "Open decision"}
            </Button>
            {!compact ? (
            <Button asChild size="sm" variant="ghost">
              <Link href={withBasePath(basePath, `/review/changes/${row.id}/canonical`)}>
                <SquarePen className="mr-2 h-4 w-4" />
                Edit then approve
              </Link>
            </Button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function DecisionWorkspace({
  selected,
  currentEvidenceSide,
  evidenceView,
  evidence,
  previewBusy,
  labelLearning,
  labelLearningBusy,
  labelLearningError,
  learningOpen,
  newFamilyLabel,
  editContext,
  editContextBusy,
  editContextError,
  decisionBusy,
  onEvidenceSideChange,
  onEvidenceViewChange,
  onDecide,
  onLearningToggle,
  onApproveAndLearnExisting,
  onApproveAndLearnCreate,
  onNewFamilyLabelChange,
  onRetryLearningContext,
  basePath = "",
  compact = false,
}: {
  selected: ReviewChange;
  currentEvidenceSide: "before" | "after";
  evidenceView: EvidenceViewMode;
  evidence: LoadedEvidence | null;
  previewBusy: "before" | "after" | null;
  labelLearning: LabelLearningPreview | null;
  labelLearningBusy: "preview" | "apply" | null;
  labelLearningError: string | null;
  learningOpen: boolean;
  newFamilyLabel: string;
  editContext: ReviewEditContext | null;
  editContextBusy: boolean;
  editContextError: string | null;
  decisionBusy: "approve" | "reject" | null;
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
}) {
  const summary = summarizeChange(selected);
  const beforeDue = formatSemanticDue((selected.before_event || {}) as Record<string, unknown>, "No previous time");
  const afterDue = formatSemanticDue((selected.after_event || {}) as Record<string, unknown>, "No new time");
  const pending = selected.review_status === "pending";
  const learningAvailable = pending && labelLearning?.status === "unresolved";
  const canonicalTimeline = canonicalTimelineLabel(editContext);
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

  function sectionVisible(section: "change" | "evidence" | "match" | "decision") {
    if (!compact) {
      return true;
    }
    return section === "change" || section === "decision";
  }

  return (
    <div className="space-y-4">
      {!compact ? (
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Decision workspace</p>
            <h2 className="mt-2 text-2xl font-semibold text-ink">{summary.title}</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge tone={selected.review_status}>{formatStatusLabel(selected.review_status)}</Badge>
            <Badge tone={changeTypeTone(selected.change_type)}>{formatStatusLabel(selected.change_type)}</Badge>
            {selected.priority_label ? <Badge tone={priorityTone(selected.priority_label)}>{formatStatusLabel(selected.priority_label)}</Badge> : null}
          </div>
        </div>
      </Card>
      ) : null}

      {sectionVisible("change") ? (
      <Card className="p-5">
        <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">What changed</p>
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">Before</p>
            <p className="mt-2 text-sm font-medium text-ink">{beforeDue}</p>
          </div>
          <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">After</p>
            <p className="mt-2 text-sm font-medium text-ink">{afterDue}</p>
          </div>
          <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">Detected</p>
            <p className="mt-2 text-sm font-medium text-ink">{formatDateTime(selected.detected_at)}</p>
          </div>
          <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">Primary source</p>
            <p className="mt-2 text-sm font-medium text-ink">{selected.primary_source ? sourceDescriptor(selected.primary_source) : "Needs source confirmation"}</p>
          </div>
        </div>
      </Card>
      ) : null}

      {!compact ? (
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Why the system thinks this</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant={currentEvidenceSide === "before" ? "secondary" : "ghost"} onClick={() => onEvidenceSideChange("before")}>
              <FileSearch className="mr-2 h-4 w-4" />
              {previewBusy === "before" ? "Loading..." : "Preview before"}
            </Button>
            <Button size="sm" variant={currentEvidenceSide === "after" ? "secondary" : "ghost"} onClick={() => onEvidenceSideChange("after")}>
              <CalendarRange className="mr-2 h-4 w-4" />
              {previewBusy === "after" ? "Loading..." : "Preview after"}
            </Button>
          </div>
        </div>

        {!compact ? (
          <>
            <div className="mt-4 flex flex-wrap gap-2">
              {selected.proposal_sources.map((source) => (
                <Badge key={`${selected.id}-${source.source_id}-${source.external_event_id || "none"}`} tone="info">
                  {sourceDescriptor(source)}
                </Badge>
              ))}
              <Badge tone="info">{confidenceLabel(selected)}</Badge>
            </div>

            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              <ChangeSummarySourceCard title="Previous source snapshot" emptyLabel="No previous source snapshot" summary={selected.change_summary?.old} />
              <ChangeSummarySourceCard title="Current source snapshot" emptyLabel="No current source snapshot" summary={selected.change_summary?.new} />
            </div>
          </>
        ) : null}

        <div className="mt-4 inline-flex flex-wrap gap-2 rounded-full border border-line/80 bg-white/60 p-2">
          <Button size="sm" variant={evidenceView === "summary" ? "primary" : "ghost"} onClick={() => onEvidenceViewChange("summary")}>
            Summary
          </Button>
          <Button size="sm" variant={evidenceView === "raw" ? "primary" : "ghost"} onClick={() => onEvidenceViewChange("raw")}>
            Raw
          </Button>
        </div>

        <div className="mt-4 rounded-[1.2rem] border border-line/80 bg-[#f2ebe1] p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm font-medium text-ink">Evidence preview</p>
            {evidence ? (
              <div className="flex flex-wrap gap-2 text-xs text-[#6d7885]">
                {evidence.payload.filename ? <span>{evidence.payload.filename}</span> : null}
                {typeof evidence.payload.event_count === "number" ? <span>{evidence.payload.event_count} events</span> : null}
                {evidence.payload.truncated ? <span>Truncated</span> : null}
              </div>
            ) : null}
          </div>
          <div className="mt-4">
            {evidence ? (
              evidenceView === "summary" ? (
                <EvidenceSummary evidence={evidence} />
              ) : (
                <pre className="whitespace-pre-wrap text-xs leading-6 text-[#314051]">{evidence.payload.preview_text || evidence.summaryFallback}</pre>
              )
            ) : (
              <p className="text-sm text-[#596270]">Choose before or after to inspect the attached evidence.</p>
            )}
          </div>
        </div>
      </Card>
      ) : (
      <CompactSection
        title="Evidence"
        open={expandedSections.evidence}
        onToggle={() => setExpandedSections((current) => ({ ...current, evidence: !current.evidence }))}
      >
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant={currentEvidenceSide === "before" ? "secondary" : "ghost"} onClick={() => onEvidenceSideChange("before")}>
              <FileSearch className="mr-2 h-4 w-4" />
              {previewBusy === "before" ? "Loading..." : "Preview before"}
            </Button>
            <Button size="sm" variant={currentEvidenceSide === "after" ? "secondary" : "ghost"} onClick={() => onEvidenceSideChange("after")}>
              <CalendarRange className="mr-2 h-4 w-4" />
              {previewBusy === "after" ? "Loading..." : "Preview after"}
            </Button>
          </div>
          <div className="inline-flex flex-wrap gap-2 rounded-full border border-line/80 bg-white/60 p-2">
            <Button size="sm" variant={evidenceView === "summary" ? "primary" : "ghost"} onClick={() => onEvidenceViewChange("summary")}>
              Summary
            </Button>
            <Button size="sm" variant={evidenceView === "raw" ? "primary" : "ghost"} onClick={() => onEvidenceViewChange("raw")}>
              Raw
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
              <p className="text-sm text-[#596270]">Choose before or after to inspect the attached evidence.</p>
            )}
          </div>
        </div>
      </CompactSection>
      )}

      {!compact ? (
      <Card className="p-5">
        <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Canonical match</p>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">Family</p>
            <p className="mt-2 text-sm font-medium text-ink">{canonicalDisplayLabel(editContext, selected)}</p>
            <p className="mt-2 text-xs text-[#596270]">
              {selected.after_event?.event_display.course_display || selected.before_event?.event_display.course_display || "Unknown course"}
            </p>
          </div>
          <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">Canonical event</p>
            <p className="mt-2 text-sm font-medium text-ink">{canonicalTimeline || "Loading canonical context..."}</p>
            <p className="mt-2 text-xs text-[#596270]">Entity UID: {selected.entity_uid}</p>
          </div>
        </div>

        {!compact ? (
          <div className="mt-4 rounded-[1.15rem] border border-line/80 bg-white/72 p-4 text-sm text-[#314051]">
            {editContextBusy ? (
              <p className="text-[#596270]">Loading…</p>
            ) : editContextError ? (
              <p className="text-[#7f3d2a]">{editContextError}</p>
            ) : editContext ? (
              <div className="grid gap-2 md:grid-cols-2">
                <p>Event name: {editContext.editable_event.event_name || "Not set"}</p>
                <p>Raw label: {editContext.editable_event.raw_type || "Not set"}</p>
                <p>Ordinal: {editContext.editable_event.ordinal ?? "N/A"}</p>
                <p>Current due: {formatSemanticDue(editContext.editable_event as unknown as Record<string, unknown>, "Not set")}</p>
              </div>
            ) : (
              <p className="text-[#596270]">Canonical context is unavailable for this change.</p>
            )}
          </div>
        ) : null}
      </Card>
      ) : (
      <CompactSection
        title="Canonical match"
        open={expandedSections.match}
        onToggle={() => setExpandedSections((current) => ({ ...current, match: !current.match }))}
      >
        <div className="space-y-3">
          <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">Family</p>
            <p className="mt-2 text-sm font-medium text-ink">{canonicalDisplayLabel(editContext, selected)}</p>
          </div>
          <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">Canonical event</p>
            <p className="mt-2 text-sm font-medium text-ink">{canonicalTimeline || "Loading canonical context..."}</p>
          </div>
        </div>
      </CompactSection>
      )}

      <Card className="p-5">
        <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Decision</p>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => onDecide("approve")} disabled={!pending || decisionBusy !== null}>
            <CheckCheck className="mr-2 h-4 w-4" />
            {decisionBusy === "approve" ? "Approving..." : "Approve"}
          </Button>
          <Button variant="danger" onClick={() => onDecide("reject")} disabled={!pending || decisionBusy !== null}>
            <XCircle className="mr-2 h-4 w-4" />
            {decisionBusy === "reject" ? "Rejecting..." : "Reject"}
          </Button>
          <Button variant="ghost" onClick={onLearningToggle} disabled={!learningAvailable || labelLearningBusy === "preview"}>
            <Sparkles className="mr-2 h-4 w-4" />
            Approve and learn
          </Button>
          {!compact ? (
            <Button asChild variant="ghost">
              <Link href={withBasePath(basePath, `/review/changes/${selected.id}/canonical`)}>
                <SquarePen className="mr-2 h-4 w-4" />
                Edit then approve
              </Link>
            </Button>
          ) : null}
        </div>

        {!pending ? (
          <div className="mt-4 rounded-[1.1rem] border border-line/80 bg-white/75 p-4 text-sm text-[#596270]">
            This change is already {formatStatusLabel(selected.review_status).toLowerCase()}.
          </div>
        ) : null}

        {pending && labelLearningBusy === "preview" ? (
          <div className="mt-4 rounded-[1.1rem] border border-line/80 bg-white/75 p-4 text-sm text-[#596270]">
            <p className="font-medium text-ink">Approve and learn</p>
            <p className="mt-2 leading-6">Loading…</p>
          </div>
        ) : null}

        {pending && labelLearningError ? (
          <div className="mt-4 rounded-[1.1rem] border border-[#efc4b5] bg-[#fff3ef] p-4 text-sm text-[#7f3d2a]">
            <p className="font-medium text-ink">Approve and learn</p>
            <p className="mt-2 leading-6">{labelLearningError}</p>
            <div className="mt-3">
              <Button size="sm" variant="ghost" onClick={onRetryLearningContext}>
                Retry learning context
              </Button>
            </div>
          </div>
        ) : null}

        {pending && labelLearning && learningOpen ? (
          <div className="mt-4 rounded-[1.1rem] border border-line/80 bg-white/75 p-4 text-sm text-[#596270]">
            <p className="font-medium text-ink">Approve and learn</p>
            <p className="mt-2 leading-6">
              {labelLearning.course_display || "Unknown"} · {labelLearning.raw_label || "Unknown"} · {labelLearning.ordinal ?? "N/A"}
            </p>
            {labelLearning.status === "resolved" ? (
              <p className="mt-3 text-[#314051]">Already resolves to {labelLearning.resolved_canonical_label || "an existing family"}.</p>
            ) : (
              <>
                <div className="mt-4 flex flex-wrap gap-2">
                  {labelLearning.families.map((family) => (
                    <Button
                      key={family.id}
                      size="sm"
                      variant="ghost"
                      disabled={labelLearningBusy === "apply"}
                      onClick={() =>
                        onApproveAndLearnExisting(family.id, labelLearning.raw_label || "label", family.canonical_label)
                      }
                    >
                      Learn as {family.canonical_label}
                    </Button>
                  ))}
                </div>
                <div className="mt-4 flex flex-wrap gap-3">
                  <Input
                    className="max-w-sm"
                    value={newFamilyLabel}
                    onChange={(event) => onNewFamilyLabelChange(event.target.value)}
                    placeholder="New family label"
                  />
                  <Button size="sm" disabled={labelLearningBusy === "apply" || !newFamilyLabel.trim()} onClick={onApproveAndLearnCreate}>
                    Create family and approve
                  </Button>
                </div>
              </>
            )}
          </div>
        ) : null}

        {!compact && pending && selected.change_type !== "removed" ? (
          <div className="mt-4 rounded-[1.1rem] border border-line/80 bg-white/75 p-4 text-sm text-[#596270]">
            <p className="font-medium text-ink">Advanced path</p>
            <div className="mt-3">
              <Button asChild size="sm" variant="ghost">
                <Link href={withBasePath(basePath, `/review/changes/${selected.id}/proposal`)}>
                  <PencilLine className="mr-2 h-4 w-4" />
                  Edit proposal
                </Link>
              </Button>
            </div>
          </div>
        ) : null}

        {compact ? (
          <div className="mt-4">
            <CompactSection
              title="More"
              open={expandedSections.extras}
              onToggle={() => setExpandedSections((current) => ({ ...current, extras: !current.extras }))}
            >
              <div className="flex flex-wrap gap-2">
                <Button asChild size="sm" variant="ghost">
                  <Link href={withBasePath(basePath, `/review/changes/${selected.id}/canonical`)}>
                    <SquarePen className="mr-2 h-4 w-4" />
                    Edit then approve
                  </Link>
                </Button>
                {selected.change_type !== "removed" ? (
                  <Button asChild size="sm" variant="ghost">
                    <Link href={withBasePath(basePath, `/review/changes/${selected.id}/proposal`)}>
                      <PencilLine className="mr-2 h-4 w-4" />
                      Edit proposal
                    </Link>
                  </Button>
                ) : null}
              </div>
            </CompactSection>
          </div>
        ) : null}
      </Card>
    </div>
  );
}

export function ReviewChangesPanel({ basePath = "" }: { basePath?: string }) {
  const [statusFilter, setStatusFilter] = useState<(typeof statusOptions)[number]>("pending");
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
  const [editContext, setEditContext] = useState<ReviewEditContext | null>(null);
  const [editContextBusy, setEditContextBusy] = useState(false);
  const [editContextError, setEditContextError] = useState<string | null>(null);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);
  const { side: drawerSide, isDesktop } = useWorkspaceLayout();

  const { data, loading, error, refresh, setData } = useApiResource<ReviewChange[]>(
    () => listReviewChanges({ review_status: statusFilter, limit: 50 }),
    [statusFilter],
  );
  const rows = useMemo(() => data || [], [data]);
  const groups = useMemo(() => groupChangesByCourse(rows), [rows]);
  const selected = rows.find((row) => row.id === selectedChangeId) || null;
  const selectedIdsSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const allVisibleSelected = rows.length > 0 && rows.every((row) => selectedIdsSet.has(row.id));

  useEffect(() => {
    if (rows.length === 0) {
      setSelectedChangeId(null);
      setSelectedIds([]);
      setEvidence(null);
      setMobileDetailOpen(false);
      return;
    }

    setSelectedIds((prev) => prev.filter((id) => rows.some((row) => row.id === id)));

    if (!selectedChangeId || !rows.some((row) => row.id === selectedChangeId)) {
      setSelectedChangeId(rows[0].id);
      setEvidence(null);
      if (statusFilter !== "pending") {
        setLearningOpen(false);
      }
    }
  }, [rows, selectedChangeId, statusFilter]);

  const markViewed = useCallback(
    async (change: ReviewChange) => {
      if (change.viewed_at) {
        return;
      }
      try {
        const updated = await markReviewChangeViewed(change.id, { viewed: true, note: "ui_opened" });
        setData((prev) => prev?.map((row) => (row.id === updated.id ? updated : row)) || prev);
      } catch {
        // Non-fatal.
      }
    },
    [setData],
  );

  const openEvidence = useCallback(
    async (change: ReviewChange, side: "before" | "after") => {
      setPreviewBusy(side);
      setCurrentEvidenceSide(side);
      await markViewed(change);
      try {
        const payload = await previewReviewChangeEvidence(change.id, side);
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

    void getReviewChangeEditContext(selected.id)
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

    void previewLabelLearning(selected.id)
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
      await decideReviewChange(selected.id, { decision, note: `ui_${decision}` });
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
      const payload = await batchDecideReviewChanges({ ids: selectedIds, decision, note: `ui_batch_${decision}` });
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
      await applyLabelLearning(selected.id, {
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
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to approve and learn" });
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
    if (!isDesktop) {
      setMobileDetailOpen(true);
    }
  }

  if (loading) return <LoadingState label="review changes" />;
  if (error) return <ReviewInboxError message={error} basePath={basePath} />;

  return (
    <div className="space-y-5">
      <Card className="animate-surface-enter relative overflow-hidden p-6 md:p-7">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.14),transparent_34%),radial-gradient(circle_at_82%_18%,rgba(215,90,45,0.12),transparent_28%)]" />
        <div className="relative space-y-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-3xl">
              <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">Changes workspace</p>
              <h3 className="mt-3 text-3xl font-semibold text-ink">Work the course inbox, but decide in context.</h3>
            </div>
            <div className="flex flex-wrap gap-2">
              {statusOptions.map((status) => (
                <Button key={status} variant={statusFilter === status ? "primary" : "ghost"} size="sm" onClick={() => setStatusFilter(status)}>
                  {formatStatusLabel(status)}
                </Button>
              ))}
            </div>
          </div>

          {banner ? (
            <Card className={banner.tone === "error" ? "border-[#efc4b5] bg-[#fff3ef] p-4" : "border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] p-4"}>
              <p className="text-sm text-[#314051]">{banner.text}</p>
            </Card>
          ) : null}

          <div className="flex flex-wrap items-center gap-3 text-sm text-[#596270]">
            <Badge tone="info">{formatStatusLabel(statusFilter)} lane</Badge>
            <span>{rows.length} visible changes</span>
            <span>•</span>
            <span>{groups.length} course group{groups.length === 1 ? "" : "s"}</span>
          </div>
        </div>
      </Card>

      <div className="grid gap-5 xl:grid-cols-[minmax(360px,0.92fr)_minmax(0,1.08fr)]">
        <Card className="p-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Inbox</p>
              <h2 className="mt-1 text-lg font-semibold text-ink">Course-grouped review lane</h2>
            </div>
            {statusFilter === "pending" ? <Badge tone="pending">{selectedIds.length} selected</Badge> : <Badge tone="info">{rows.length} rows</Badge>}
          </div>

      {statusFilter === "pending" && isDesktop ? (
            <div className="mt-4 flex flex-wrap items-center justify-between gap-4 rounded-[1.15rem] border border-line/80 bg-white/65 p-4">
              <label className="flex items-center gap-3 text-sm text-[#314051]">
                <Checkbox aria-label="Select all visible review changes" checked={allVisibleSelected} onChange={(event) => toggleVisibleSelection(event.currentTarget.checked)} />
                Select visible
              </label>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="ghost" disabled={selectedIds.length === 0 || batchBusy === "reject"} onClick={() => void decideBatch("reject")}>
                  <XCircle className="mr-2 h-4 w-4" />
                  {batchBusy === "reject" ? "Rejecting..." : "Reject selected"}
                </Button>
                <Button size="sm" disabled={selectedIds.length === 0 || batchBusy === "approve"} onClick={() => void decideBatch("approve")}>
                  <CheckCheck className="mr-2 h-4 w-4" />
                  {batchBusy === "approve" ? "Approving..." : "Approve selected"}
                </Button>
              </div>
            </div>
          ) : null}

          <div className="mt-5 space-y-5">
            {rows.length === 0 ? (
              <EmptyState title="No changes in this lane" description="Switch filters or run another sync to generate new review work." />
            ) : (
              groups.map((group) => (
                <div key={group.course} className="space-y-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Course</p>
                      <h3 className="mt-1 text-sm font-semibold text-ink">{group.course}</h3>
                    </div>
                    <Badge tone="info">{group.changes.length} change{group.changes.length === 1 ? "" : "s"}</Badge>
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

        <div className="hidden xl:block">
          {selected ? (
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
              onEvidenceSideChange={(side) => void openEvidence(selected, side)}
              onEvidenceViewChange={setEvidenceView}
              onDecide={(decision) => void decide(decision)}
              onLearningToggle={() => setLearningOpen((current) => !current)}
              onApproveAndLearnExisting={(familyId, rawLabel, canonicalLabel) =>
                void approveAndLearn({
                  mode: "add_alias",
                  family_id: familyId,
                  successText: `Approved and learned ${rawLabel} as ${canonicalLabel}.`,
                })
              }
              onApproveAndLearnCreate={() =>
                void approveAndLearn({
                  mode: "create_family",
                  canonical_label: newFamilyLabel.trim(),
                  successText: `Created family ${newFamilyLabel.trim()} and approved the change.`,
                })
              }
              onNewFamilyLabelChange={setNewFamilyLabel}
              onRetryLearningContext={() => setLabelLearningReloadNonce((current) => current + 1)}
              basePath={basePath}
              compact={false}
            />
          ) : (
            <Card className="animate-surface-enter p-6 text-sm text-[#596270]">Select a change to open the decision workspace.</Card>
          )}
        </div>
      </div>

      <Sheet
        open={mobileDetailOpen && selected !== null}
        onOpenChange={(open) => {
          setMobileDetailOpen(open);
        }}
      >
        <SheetContent side={drawerSide} className="overflow-y-auto xl:hidden">
          {selected ? (
            <>
              <SheetHeader>
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Decision workspace</p>
                  <SheetTitle className="mt-3 leading-tight">{summarizeChange(selected).title}</SheetTitle>
                  <SheetDescription>Review the change in focused sections.</SheetDescription>
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
                  onEvidenceSideChange={(side) => void openEvidence(selected, side)}
                  onEvidenceViewChange={setEvidenceView}
                  onDecide={(decision) => void decide(decision)}
                  onLearningToggle={() => setLearningOpen((current) => !current)}
                  onApproveAndLearnExisting={(familyId, rawLabel, canonicalLabel) =>
                    void approveAndLearn({
                      mode: "add_alias",
                      family_id: familyId,
                      successText: `Approved and learned ${rawLabel} as ${canonicalLabel}.`,
                    })
                  }
                  onApproveAndLearnCreate={() =>
                    void approveAndLearn({
                      mode: "create_family",
                      canonical_label: newFamilyLabel.trim(),
                      successText: `Created family ${newFamilyLabel.trim()} and approved the change.`,
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
    </div>
  );
}
