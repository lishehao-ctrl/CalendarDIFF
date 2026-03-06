"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CalendarRange, CheckCheck, Eye, FileSearch, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { backendFetch } from "@/lib/backend";
import { extractEventSubtitle, formatDateTime, formatStatusLabel, sourceDescriptor, summarizeChange } from "@/lib/presenters";
import type { ReviewChange } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

const statusOptions = ["pending", "approved", "rejected"] as const;

type EvidenceState = {
  side: "before" | "after";
  text: string;
  filename?: string;
  eventCount?: number;
  truncated?: boolean;
} | null;

export function ReviewChangesPanel() {
  const [statusFilter, setStatusFilter] = useState<(typeof statusOptions)[number]>("pending");
  const [selectedChangeId, setSelectedChangeId] = useState<number | null>(null);
  const [evidence, setEvidence] = useState<EvidenceState>(null);
  const [previewBusy, setPreviewBusy] = useState<"before" | "after" | null>(null);
  const [decisionBusy, setDecisionBusy] = useState<"approve" | "reject" | null>(null);

  const { data, loading, error, refresh, setData } = useResource<ReviewChange[]>(`/review/changes?review_status=${statusFilter}&limit=50`);
  const rows = useMemo(() => data || [], [data]);
  const selected = rows.find((row) => row.id === selectedChangeId) || rows[0] || null;

  useEffect(() => {
    if (rows.length === 0) {
      setSelectedChangeId(null);
      setEvidence(null);
      return;
    }

    if (!selectedChangeId || !rows.some((row) => row.id === selectedChangeId)) {
      setSelectedChangeId(rows[0].id);
    }
  }, [rows, selectedChangeId]);

  const markViewed = useCallback(async (change: ReviewChange) => {
    if (change.viewed_at) {
      return;
    }

    try {
      const updated = await backendFetch<ReviewChange>(`/review/changes/${change.id}/views`, {
        method: "PATCH",
        body: JSON.stringify({ viewed: true, note: "ui_opened" })
      });
      setData((prev) => prev?.map((row) => (row.id === updated.id ? updated : row)) || prev);
    } catch {
      // Non-fatal for the UI; selection should still open.
    }
  }, [setData]);

  const openEvidence = useCallback(async (change: ReviewChange, side: "before" | "after") => {
    setPreviewBusy(side);
    setSelectedChangeId(change.id);
    await markViewed(change);
    try {
      const payload = await backendFetch<{
        preview_text?: string;
        filename?: string;
        event_count?: number;
        truncated?: boolean;
        events?: Array<{ summary?: string | null; dtstart?: string | null; location?: string | null }>;
      }>(`/review/changes/${change.id}/evidence/${side}/preview`);
      const fallback =
        payload.events?.map((event) => [event.summary || "(untitled)", event.dtstart, event.location].filter(Boolean).join(" · ")).join("\n") ||
        "No preview text available.";
      setEvidence({
        side,
        text: payload.preview_text || fallback,
        filename: payload.filename,
        eventCount: payload.event_count,
        truncated: payload.truncated
      });
    } catch (err) {
      setEvidence({
        side,
        text: err instanceof Error ? err.message : "Unable to load evidence preview."
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
    void openEvidence(selected, "after");
  }, [openEvidence, selected]);

  async function decide(decision: "approve" | "reject") {
    if (!selected) {
      return;
    }
    setDecisionBusy(decision);
    try {
      await backendFetch(`/review/changes/${selected.id}/decisions`, {
        method: "POST",
        body: JSON.stringify({ decision, note: `ui_${decision}` })
      });
      await refresh();
    } finally {
      setDecisionBusy(null);
    }
  }

  if (loading) return <LoadingState label="review changes" />;
  if (error) return <ErrorState message={error} />;

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
          <p className="mt-3 text-3xl font-semibold">{evidence ? formatStatusLabel(evidence.side) : "Idle"}</p>
          <p className="mt-2 text-sm text-[#596270]">Preview the before or after payload attached to the selected change.</p>
        </Card>
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.08fr_0.92fr]">
        <Card className="p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Moderation queue</p>
              <h3 className="mt-3 text-2xl font-semibold">Review change inbox</h3>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                Select a row to inspect evidence, then approve the canonical version or reject the proposal before it pollutes downstream state.
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

          <div className="mt-5 space-y-3">
            {rows.length === 0 ? (
              <EmptyState title="Nothing in this lane" description="Switch filters or run another sync to generate review work." />
            ) : (
              rows.map((row) => {
                const summary = summarizeChange(row);
                const selectedRow = row.id === selected?.id;
                return (
                  <button
                    key={row.id}
                    className={selectedRow ? "w-full text-left" : "w-full text-left"}
                    onClick={() => {
                      setSelectedChangeId(row.id);
                      void markViewed(row);
                    }}
                    type="button"
                  >
                    <Card className={selectedRow ? "border-[rgba(31,94,255,0.35)] bg-white p-5" : "bg-white/60 p-5 transition hover:-translate-y-0.5 hover:bg-white"}>
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
                            {row.priority_label ? (
                              <>
                                <span>•</span>
                                <span>{formatStatusLabel(row.priority_label)}</span>
                              </>
                            ) : null}
                          </div>
                          <div className="mt-3 flex flex-wrap gap-2">
                            {row.proposal_sources.map((source) => (
                              <Badge key={`${row.id}-${source.source_id}-${source.external_event_id || "none"}`} tone="info">
                                {sourceDescriptor(source)}
                              </Badge>
                            ))}
                          </div>
                        </div>
                        <div className="flex items-center gap-2 text-sm text-[#6d7885]">
                          <Eye className="h-4 w-4" />
                          {row.viewed_at ? formatDateTime(row.viewed_at, "Viewed") : "Unviewed"}
                        </div>
                      </div>
                    </Card>
                  </button>
                );
              })
            )}
          </div>
        </Card>

        <div className="space-y-5">
          <Card className="p-6">
            {selected ? (
              <>
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Selected change</p>
                    <h3 className="mt-3 text-2xl font-semibold">{summarizeChange(selected).title}</h3>
                    <p className="mt-2 text-sm leading-6 text-[#596270]">
                      {extractEventSubtitle(selected.after_json) || extractEventSubtitle(selected.before_json) || `Event ${selected.event_uid}`}
                    </p>
                  </div>
                  <Badge tone={selected.review_status}>{formatStatusLabel(selected.review_status)}</Badge>
                </div>

                <div className="mt-5 grid gap-3 md:grid-cols-2">
                  <div className="rounded-[1.2rem] border border-line/80 bg-white/60 p-4 text-sm text-[#314051]">
                    <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Timeline</p>
                    <p className="mt-2">Detected {formatDateTime(selected.detected_at)}</p>
                    <p className="mt-1">Deliver after {formatDateTime(selected.deliver_after, "Not scheduled")}</p>
                  </div>
                  <div className="rounded-[1.2rem] border border-line/80 bg-white/60 p-4 text-sm text-[#314051]">
                    <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Change summary</p>
                    <p className="mt-2">Old value: {formatDateTime(selected.change_summary?.old?.value_time, "N/A")}</p>
                    <p className="mt-1">New value: {formatDateTime(selected.change_summary?.new?.value_time, "N/A")}</p>
                  </div>
                </div>

                <div className="mt-5 flex flex-wrap gap-2">
                  <Button size="sm" variant={evidence?.side === "before" ? "secondary" : "ghost"} onClick={() => void openEvidence(selected, "before")}>
                    <FileSearch className="mr-2 h-4 w-4" />
                    {previewBusy === "before" ? "Loading..." : "Preview before"}
                  </Button>
                  <Button size="sm" variant={evidence?.side === "after" ? "secondary" : "ghost"} onClick={() => void openEvidence(selected, "after")}>
                    <CalendarRange className="mr-2 h-4 w-4" />
                    {previewBusy === "after" ? "Loading..." : "Preview after"}
                  </Button>
                </div>

                <div className="mt-4 rounded-[1.25rem] border border-line/80 bg-[#f2ebe1] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-sm font-medium text-ink">Evidence preview</p>
                    {evidence ? (
                      <div className="flex flex-wrap gap-2 text-xs text-[#6d7885]">
                        {evidence.filename ? <span>{evidence.filename}</span> : null}
                        {typeof evidence.eventCount === "number" ? <span>{evidence.eventCount} events</span> : null}
                        {evidence.truncated ? <span>Truncated</span> : null}
                      </div>
                    ) : null}
                  </div>
                  <pre className="mt-3 min-h-[260px] whitespace-pre-wrap text-xs leading-6 text-[#314051]">
                    {evidence?.text || "Select a preview mode to inspect source evidence."}
                  </pre>
                </div>

                <div className="mt-5 flex flex-wrap gap-3">
                  <Button onClick={() => void decide("approve")} disabled={decisionBusy !== null}>
                    <CheckCheck className="mr-2 h-4 w-4" />
                    {decisionBusy === "approve" ? "Approving..." : "Approve change"}
                  </Button>
                  <Button variant="danger" onClick={() => void decide("reject")} disabled={decisionBusy !== null}>
                    <XCircle className="mr-2 h-4 w-4" />
                    {decisionBusy === "reject" ? "Rejecting..." : "Reject change"}
                  </Button>
                </div>
              </>
            ) : (
              <EmptyState title="No change selected" description="Pick a row from the queue to inspect before/after evidence." />
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
