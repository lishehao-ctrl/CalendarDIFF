"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CalendarRange, CheckCheck, Eye, FileSearch, PencilLine, SquarePen, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { Sheet, SheetContent, SheetDescription, SheetDismissButton, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { applyLabelLearning, batchDecideReviewChanges, decideReviewChange, listReviewChanges, markReviewChangeViewed, previewLabelLearning, previewReviewChangeEvidence } from "@/lib/api/review";
import { formatDateTime, formatSemanticDue, formatStatusLabel, sourceDescriptor, sourceKindDescriptor, summarizeChange } from "@/lib/presenters";
import type { EvidencePreviewResponse, LabelLearningPreview, ReviewBatchDecisionResponse, ReviewChange } from "@/lib/types";
import { useApiResource } from "@/lib/use-api-resource";

const statusOptions = ["pending", "approved", "rejected"] as const;

type Banner = {
  tone: "info" | "error";
  text: string;
} | null;

type ChangeSummarySide = NonNullable<ReviewChange["change_summary"]>["old"];
type EvidenceViewMode = "summary" | "raw";

type LoadedEvidence = {
  payload: EvidencePreviewResponse;
  summaryFallback: string;
};

type StructuredEvidenceItem = EvidencePreviewResponse["structured_items"][number];

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

function ReviewInboxError({ message }: { message: string }) {
  const showSourcesCta = message.includes("Connect at least one active source in Sources");
  return <ErrorState message={message} actionLabel={showSourcesCta ? "Open Sources" : undefined} actionHref={showSourcesCta ? "/sources" : undefined} />;
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
  const structuredItems = evidence.payload.structured_items?.length
    ? evidence.payload.structured_items
    : renderFallbackStructuredItems(evidence);

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
                <span className="text-[#6d7885]">Link:</span> <a className="text-cobalt underline-offset-4 hover:underline" href={item.url} target="_blank" rel="noreferrer">{item.url}</a>
              </p>
            ) : null}
          </div>
          {item.description ? <p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-[#596270]">{item.description}</p> : null}
        </div>
      ))}
    </div>
  );
}

function useResponsiveSheetSide() {
  const [side, setSide] = useState<"right" | "bottom">("right");
  useEffect(() => {
    function update() {
      setSide(window.innerWidth < 1024 ? "bottom" : "right");
    }
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  return side;
}

export function ReviewChangesPanel() {
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
  const [newFamilyLabel, setNewFamilyLabel] = useState("");
  const [banner, setBanner] = useState<Banner>(null);
  const drawerSide = useResponsiveSheetSide();

  const { data, loading, error, refresh, setData } = useApiResource<ReviewChange[]>(() => listReviewChanges({ review_status: statusFilter, limit: 50 }), [statusFilter]);
  const rows = useMemo(() => data || [], [data]);
  const selected = rows.find((row) => row.id === selectedChangeId) || null;
  const selectedIdsSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const allVisibleSelected = rows.length > 0 && rows.every((row) => selectedIdsSet.has(row.id));

  useEffect(() => {
    if (rows.length === 0) {
      setSelectedChangeId(null);
      setSelectedIds([]);
      setEvidence(null);
      return;
    }
    setSelectedIds((prev) => prev.filter((id) => rows.some((row) => row.id === id)));
    if (selectedChangeId && !rows.some((row) => row.id === selectedChangeId)) {
      setSelectedChangeId(null);
      setEvidence(null);
    }
  }, [rows, selectedChangeId]);

  const markViewed = useCallback(async (change: ReviewChange) => {
    if (change.viewed_at) {
      return;
    }
    try {
      const updated = await markReviewChangeViewed(change.id, { viewed: true, note: "ui_opened" });
      setData((prev) => prev?.map((row) => (row.id === updated.id ? updated : row)) || prev);
    } catch {
      // Non-fatal.
    }
  }, [setData]);

  const openEvidence = useCallback(async (change: ReviewChange, side: "before" | "after") => {
    setPreviewBusy(side);
    setCurrentEvidenceSide(side);
    await markViewed(change);
    try {
      const payload = await previewReviewChangeEvidence(change.id, side);
      const fallback = payload.events?.map((event) => [event.summary || "(untitled)", event.dtstart, event.location].filter(Boolean).join(" · ")).join("\n") || "No preview text available.";
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
  }, [markViewed]);

  useEffect(() => {
    if (!selected) {
      setEvidence(null);
      return;
    }
    void openEvidence(selected, currentEvidenceSide);
  }, [openEvidence, selected, currentEvidenceSide]);

  useEffect(() => {
    if (!selected || selected.review_status !== "pending") {
      setLabelLearning(null);
      setLabelLearningBusy(null);
      setLabelLearningError(null);
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
        if (cancelled) return;
        setLabelLearningBusy((current) => (current === "preview" ? null : current));
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
      setSelectedChangeId(null);
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
        text: payload.failed > 0 ? `${payload.succeeded} updated, ${payload.failed} skipped.` : decision === "approve" ? `${payload.succeeded} changes approved.` : `${payload.succeeded} changes rejected.`
      });
      if (selected && selectedIds.includes(selected.id)) {
        setSelectedChangeId(null);
      }
      await refresh();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Batch decision failed" });
    } finally {
      setBatchBusy(null);
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

  if (loading) return <LoadingState label="review changes" />;
  if (error) return <ReviewInboxError message={error} />;

  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-4">
        <Card className="p-5 md:col-span-2">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Current lane</p>
          <p className="mt-3 text-3xl font-semibold">{formatStatusLabel(statusFilter)}</p>
          <p className="mt-2 text-sm text-[#596270]">Filter changes by moderation state. Pending is the primary operational queue.</p>
        </Card>
        <Card className="p-5">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Visible rows</p>
          <p className="mt-3 text-3xl font-semibold">{rows.length}</p>
          <p className="mt-2 text-sm text-[#596270]">Current window size for the selected moderation lane.</p>
        </Card>
        <Card className="p-5">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Evidence mode</p>
          <p className="mt-3 text-3xl font-semibold">{formatStatusLabel(currentEvidenceSide)}</p>
          <p className="mt-2 text-sm text-[#596270]">Default drawer preview opens in Summary mode with the most recent evidence side.</p>
        </Card>
      </div>

      {banner ? (
        <Card className={banner.tone === "error" ? "border-[#efc4b5] bg-[#fff3ef] p-4" : "border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] p-4"}>
          <p className="text-sm text-[#314051]">{banner.text}</p>
        </Card>
      ) : null}

      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Moderation queue</p>
            <h3 className="mt-3 text-xl font-semibold">Review change inbox</h3>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[#596270]">
              Select rows for batch decisions, or open a change drawer to inspect evidence and make a canonical-first edit.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {statusOptions.map((status) => (
              <Button key={status} variant={statusFilter === status ? "primary" : "ghost"} size="sm" onClick={() => setStatusFilter(status)}>
                {formatStatusLabel(status)}
              </Button>
            ))}
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-center justify-between gap-4 rounded-[1.2rem] border border-line/80 bg-white/60 p-4">
          <div className="flex items-center gap-3">
            <Checkbox aria-label="Select all visible review changes" checked={allVisibleSelected} onChange={(event) => toggleVisibleSelection(event.currentTarget.checked)} />
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Batch actions</p>
              <p className="mt-1 text-sm text-[#314051]">{selectedIds.length} selected</p>
            </div>
          </div>
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

        <div className="mt-5 space-y-3">
          {rows.length === 0 ? (
            <EmptyState title="Nothing in this lane" description="Switch filters or run another sync to generate review work." />
          ) : (
            rows.map((row) => {
              const summary = summarizeChange(row);
              return (
                <Card key={row.id} className={selectedChangeId === row.id ? "border-[rgba(31,94,255,0.35)] bg-white p-5" : "bg-white/60 p-5 transition hover:-translate-y-0.5 hover:bg-white"}>
                  <div className="flex items-start gap-4">
                    <div className="pt-1">
                      <Checkbox
                        aria-label={`Select review change ${row.id}`}
                        checked={selectedIdsSet.has(row.id)}
                        onClick={(event) => event.stopPropagation()}
                        onChange={(event) => toggleRowSelection(row.id, event.currentTarget.checked)}
                      />
                    </div>
                    <button
                      className="min-w-0 flex-1 text-left"
                      onClick={() => {
                        setSelectedChangeId(row.id);
                        setCurrentEvidenceSide("after");
                      }}
                      type="button"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-4">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-3">
                            <h4 className="text-lg font-semibold text-ink">{summary.title}</h4>
                            <Badge tone={row.review_status}>{formatStatusLabel(row.review_status)}</Badge>
                            {row.viewed_at ? <Badge tone="info">Viewed</Badge> : <Badge tone="pending">New</Badge>}
                          </div>
                          {summary.subtitle ? <p className="mt-2 text-sm text-[#314051]">{summary.subtitle}</p> : null}
                          <div className="mt-3 flex flex-wrap gap-2 text-xs text-[#6d7885]">
                            <span>{formatStatusLabel(row.change_type)}</span>
                            <span>•</span>
                            <span>Detected {formatDateTime(row.detected_at, "Unknown")}</span>
                            {row.priority_label ? <><span>•</span><span>{formatStatusLabel(row.priority_label)}</span></> : null}
                          </div>
                          {row.proposal_sources.length > 0 ? (
                            <div className="mt-4">
                              <p className="text-[11px] uppercase tracking-[0.18em] text-[#6d7885]">Sources</p>
                              <div className="mt-2 flex flex-wrap gap-2">
                                {row.proposal_sources.map((source) => (
                                  <Badge key={`${row.id}-${source.source_id}-${source.external_event_id || "none"}`} tone="info">
                                    {sourceDescriptor(source)}
                                  </Badge>
                                ))}
                              </div>
                            </div>
                          ) : null}
                          <div className="mt-4 flex flex-wrap gap-2">
                            <Button asChild size="sm" variant="ghost">
                              <Link href={`/review/changes/${row.id}/canonical`} onClick={(event) => event.stopPropagation()}>
                                <SquarePen className="mr-2 h-4 w-4" />
                                Edit canonical
                              </Link>
                            </Button>
                          </div>
                        </div>
                        <div className="flex items-center gap-2 text-sm text-[#6d7885]">
                          <Eye className="h-4 w-4" />
                          {row.viewed_at ? formatDateTime(row.viewed_at, "Viewed") : "Unviewed"}
                        </div>
                      </div>
                    </button>
                  </div>
                </Card>
              );
            })
          )}
        </div>
      </Card>

      <Sheet open={selected !== null} onOpenChange={(open) => {
        if (!open) {
          setSelectedChangeId(null);
          setEvidence(null);
          return;
        }
      }}>
        <SheetContent side={drawerSide} className="overflow-y-auto">
          {selected ? (
            <>
              <SheetHeader>
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Selected change</p>
                  <SheetTitle className="mt-3">{summarizeChange(selected).title}</SheetTitle>
                  <SheetDescription>
                    {formatSemanticDue((selected.after_event || selected.before_event || {}) as unknown as Record<string, unknown>, "Event")}
                  </SheetDescription>
                </div>
                <div className="flex items-center gap-3">
                  <Badge tone={selected.review_status}>{formatStatusLabel(selected.review_status)}</Badge>
                  <SheetDismissButton />
                </div>
              </SheetHeader>

              <div className="mt-6 space-y-5">
                <Card className="bg-white/60 p-5">
                  <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Summary</p>
                  <div className="mt-4 grid gap-3 lg:grid-cols-2">
                    <div className="rounded-[1.2rem] border border-line/80 bg-white/75 p-4 text-sm text-[#314051]">
                      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Timeline</p>
                      <p className="mt-2">Detected {formatDateTime(selected.detected_at)}</p>
                      <p className="mt-1">Deliver after {formatDateTime(selected.deliver_after, "Not scheduled")}</p>
                    </div>
                    <div className="rounded-[1.2rem] border border-line/80 bg-white/75 p-4 text-sm text-[#314051]">
                      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Change type</p>
                      <p className="mt-2 font-medium text-ink">{formatStatusLabel(selected.change_type)}</p>
                      <p className="mt-1 text-sm text-[#596270]">This change is currently in the {formatStatusLabel(selected.review_status)} lane.</p>
                    </div>
                  </div>
                  <div className="mt-4 grid gap-3 lg:grid-cols-2">
                    <ChangeSummarySourceCard title="Previous source" emptyLabel="No previous source" summary={selected.change_summary?.old} />
                    <ChangeSummarySourceCard title="Current source" emptyLabel="No current source" summary={selected.change_summary?.new} />
                  </div>
                </Card>

                <Card className="bg-white/60 p-5">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Evidence</p>
                      <p className="mt-2 text-sm leading-6 text-[#596270]">Start with a readable summary, then switch to raw ICS if you need to inspect the underlying source payload.</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button size="sm" variant={currentEvidenceSide === "before" ? "secondary" : "ghost"} onClick={() => void openEvidence(selected, "before")}>
                        <FileSearch className="mr-2 h-4 w-4" />
                        {previewBusy === "before" ? "Loading..." : "Preview before"}
                      </Button>
                      <Button size="sm" variant={currentEvidenceSide === "after" ? "secondary" : "ghost"} onClick={() => void openEvidence(selected, "after")}>
                        <CalendarRange className="mr-2 h-4 w-4" />
                        {previewBusy === "after" ? "Loading..." : "Preview after"}
                      </Button>
                    </div>
                  </div>
                  <div className="mt-4 inline-flex flex-wrap gap-2 rounded-full border border-line/80 bg-white/60 p-2">
                    <Button size="sm" variant={evidenceView === "summary" ? "primary" : "ghost"} onClick={() => setEvidenceView("summary")}>Summary</Button>
                    <Button size="sm" variant={evidenceView === "raw" ? "primary" : "ghost"} onClick={() => setEvidenceView("raw")}>Raw</Button>
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

                <Card className="bg-white/60 p-5">
                  <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Actions</p>
                  <div className="mt-4 flex flex-wrap gap-3">
                    <Button asChild>
                      <Link href={`/review/changes/${selected.id}/canonical`}>
                        <SquarePen className="mr-2 h-4 w-4" />
                        Edit canonical
                      </Link>
                    </Button>
                    <Button onClick={() => void decide("approve")} disabled={decisionBusy !== null}>
                      <CheckCheck className="mr-2 h-4 w-4" />
                      {decisionBusy === "approve" ? "Approving..." : "Approve"}
                    </Button>
                    <Button variant="danger" onClick={() => void decide("reject")} disabled={decisionBusy !== null}>
                      <XCircle className="mr-2 h-4 w-4" />
                      {decisionBusy === "reject" ? "Rejecting..." : "Reject"}
                    </Button>
                  </div>
                  {selected.review_status === "pending" && labelLearningBusy === "preview" ? (
                    <div className="mt-4 rounded-[1.1rem] border border-line/80 bg-white/75 p-4 text-sm text-[#596270]">
                      <p className="font-medium text-ink">Label learning</p>
                      <p className="mt-2 leading-6">Loading course label context…</p>
                    </div>
                  ) : null}

                  {selected.review_status === "pending" && labelLearningError ? (
                    <div className="mt-4 rounded-[1.1rem] border border-[#efc4b5] bg-[#fff3ef] p-4 text-sm text-[#7f3d2a]">
                      <p className="font-medium text-ink">Label learning</p>
                      <p className="mt-2 leading-6">{labelLearningError}</p>
                      <div className="mt-3">
                        <Button size="sm" variant="ghost" onClick={() => setLabelLearningReloadNonce((current) => current + 1)}>
                          Retry learning context
                        </Button>
                      </div>
                    </div>
                  ) : null}

                  {selected.review_status === "pending" && labelLearning ? (
                    <div className="mt-4 rounded-[1.1rem] border border-line/80 bg-white/75 p-4 text-sm text-[#596270]">
                      <p className="font-medium text-ink">Label learning</p>
                      <p className="mt-2 leading-6">Course: {labelLearning.course_display || 'Unknown'} · Raw label: {labelLearning.raw_label || 'Unknown'} · Ordinal: {labelLearning.ordinal ?? 'N/A'}</p>
                      {labelLearning.status === 'resolved' ? (
                        <p className="mt-2 text-[#314051]">Already resolved to {labelLearning.resolved_canonical_label || 'existing family'}.</p>
                      ) : (
                        <>
                          <div className="mt-3 flex flex-wrap gap-2">
                            {labelLearning.families.map((family) => (
                              <Button
                                key={family.id}
                                size="sm"
                                variant="ghost"
                                disabled={labelLearningBusy === 'apply'}
                                onClick={() => {
                                  setLabelLearningBusy('apply');
                                  setLabelLearningError(null);
                                  void applyLabelLearning(selected.id, { mode: 'add_alias', family_id: family.id })
                                    .then(async () => {
                                      setBanner({ tone: 'info', text: `Learned ${labelLearning.raw_label || 'label'} as ${family.canonical_label}.` });
                                      await refresh();
                                    })
                                    .catch((err) => setBanner({ tone: 'error', text: err instanceof Error ? err.message : 'Unable to learn alias' }))
                                    .finally(() => setLabelLearningBusy(null));
                                }}
                              >
                                Learn as {family.canonical_label}
                              </Button>
                            ))}
                          </div>
                          <div className="mt-3 flex flex-wrap gap-3">
                            <input
                              className="h-10 rounded-2xl border border-line bg-white/80 px-4 text-sm text-ink outline-none transition placeholder:text-[#7d8794] focus:border-cobalt focus:bg-white"
                              value={newFamilyLabel}
                              onChange={(event) => setNewFamilyLabel(event.target.value)}
                              placeholder="New family label"
                            />
                            <Button
                              size="sm"
                              disabled={labelLearningBusy === 'apply' || !newFamilyLabel.trim()}
                              onClick={() => {
                                setLabelLearningBusy('apply');
                                setLabelLearningError(null);
                                void applyLabelLearning(selected.id, { mode: 'create_family', canonical_label: newFamilyLabel.trim() })
                                  .then(async () => {
                                    setBanner({ tone: 'info', text: `Created family ${newFamilyLabel.trim()} and learned this label.` });
                                    await refresh();
                                  })
                                  .catch((err) => setBanner({ tone: 'error', text: err instanceof Error ? err.message : 'Unable to create family' }))
                                  .finally(() => setLabelLearningBusy(null));
                              }}
                            >
                              Create family & learn
                            </Button>
                          </div>
                        </>
                      )}
                    </div>
                  ) : null}

                  {selected.review_status === "pending" && selected.change_type !== "removed" ? (
                    <div className="mt-4 rounded-[1.1rem] border border-line/80 bg-white/75 p-4 text-sm text-[#596270]">
                      <p className="font-medium text-ink">Advanced path</p>
                      <p className="mt-2 leading-6">Need to keep the proposal-review workflow instead of applying a direct canonical correction? Use the lower-priority proposal editor.</p>
                      <div className="mt-3">
                        <Button asChild size="sm" variant="ghost">
                          <Link href={`/review/changes/${selected.id}/proposal`}>
                            <PencilLine className="mr-2 h-4 w-4" />
                            Edit proposal
                          </Link>
                        </Button>
                      </div>
                    </div>
                  ) : null}
                </Card>
              </div>
            </>
          ) : null}
        </SheetContent>
      </Sheet>
    </div>
  );
}
