import { ExternalLink, Loader2, RefreshCw } from "lucide-react";

import { SectionState } from "@/components/dashboard/section-state";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { deriveChangeSummary, formatSummaryDate } from "@/lib/change-summary";
import { ChangeFeedRecord, ChangeRecord, ChangeSummarySide } from "@/lib/types";
import type { ChangeFilter, EvidencePreviewState } from "@/lib/hooks/use-feed-data";

type DiffSectionProps = {
  changeFilter: ChangeFilter;
  onChangeFilter: (value: ChangeFilter) => void;
  changeSourceTypeFilter: "all" | "email" | "ics";
  onChangeSourceTypeFilter: (value: "all" | "email" | "ics") => void;
  changesError: string | null;
  changesLoading: boolean;
  filteredChanges: ChangeRecord[];
  changeNotes: Record<number, string>;
  onChangeNote: (changeId: number, note: string) => void;
  onToggleViewed: (change: ChangeRecord) => void | Promise<void>;
  evidencePreviews: Record<string, EvidencePreviewState>;
  onPreviewEvidence: (changeId: number, side: "before" | "after") => void | Promise<void>;
  onRefreshChanges: () => void | Promise<void>;
  getTaskDisplayTitle: (uid: string, title: string) => string;
  getCourseDisplayLabel: (label: string) => string;
};

export function DiffSection({
  changeFilter,
  onChangeFilter,
  changeSourceTypeFilter,
  onChangeSourceTypeFilter,
  changesError,
  changesLoading,
  filteredChanges,
  changeNotes,
  onChangeNote,
  onToggleViewed,
  evidencePreviews,
  onPreviewEvidence,
  onRefreshChanges,
  getTaskDisplayTitle,
  getCourseDisplayLabel,
}: DiffSectionProps) {
  return (
    <section id="diff" className="section-anchor">
      <Card className="animate-in">
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle>Diff Review</CardTitle>
              <CardDescription>Review change records, toggle viewed state, and inspect structured ICS evidence.</CardDescription>
            </div>
            <Button variant="secondary" onClick={() => void onRefreshChanges()} disabled={changesLoading}>
              {changesLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
              Refresh Changes
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          <div className="sticky top-2 z-10 rounded-2xl border border-line bg-white/95 p-3 shadow-card backdrop-blur-sm">
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-[150px]">
                <p className="mb-2 text-sm font-medium text-ink">View</p>
                <Tabs value={changeFilter} onValueChange={(value) => onChangeFilter(value as ChangeFilter)}>
                  <TabsList>
                    <TabsTrigger value="all">
                      All
                    </TabsTrigger>
                    <TabsTrigger value="unread">Unread</TabsTrigger>
                  </TabsList>
                </Tabs>
              </div>

              <div className="min-w-[190px] flex-1 space-y-2">
                <Label htmlFor="change-source-type">Input Type</Label>
                <Select
                  id="change-source-type"
                  value={changeSourceTypeFilter}
                  onChange={(event) => onChangeSourceTypeFilter(event.target.value as "all" | "email" | "ics")}
                >
                  <option value="all">All Inputs</option>
                  <option value="email">Email Only</option>
                  <option value="ics">Calendar Only</option>
                </Select>
              </div>
            </div>
          </div>

          <SectionState
            isLoading={changesLoading}
            error={changesError}
            isEmpty={!changesLoading && !changesError && !filteredChanges.length}
            loadingRows={2}
            errorTitle="Change List Failed"
            emptyTitle="No Changes"
            emptyDescription="No changes for the selected filter criteria."
          >
            <div className="stagger-fade space-y-3">
              {filteredChanges.map((change) => {
                const beforeJson = change.before_json ?? {};
                const afterJson = change.after_json ?? {};
                const rawTitle = String((afterJson.title ?? beforeJson.title ?? change.event_uid) as string);
                const rawCourse = String((afterJson.course_label ?? beforeJson.course_label ?? "Unknown") as string);
                const summary = deriveChangeSummary(change as ChangeFeedRecord);
                const displayTitle = getTaskDisplayTitle(change.event_uid, rawTitle);
                const displayCourse = getCourseDisplayLabel(rawCourse);
                const viewed = change.viewed_at !== null;
                const sourceType = readString((change as Record<string, unknown>).input_type) ?? "ics";
                const priorityLabel = readString((change as Record<string, unknown>).priority_label) ?? (sourceType === "email" ? "high" : "normal");
                const notificationState = readString((change as Record<string, unknown>).notification_state);
                const gmailMessageId = readString(afterJson.gmail_message_id) ?? readString(beforeJson.gmail_message_id);
                const isEmailChange = gmailMessageId !== null;
                const gmailSubject = readString(afterJson.subject) ?? readString(beforeJson.subject) ?? displayTitle;
                const gmailSnippet = readString(afterJson.snippet) ?? readString(beforeJson.snippet);
                const gmailInternalDate = readString(afterJson.internal_date) ?? readString(beforeJson.internal_date);
                const gmailFrom = readString(afterJson.from) ?? readString(beforeJson.from);
                const openInGmailUrl = readString(afterJson.open_in_gmail_url) ?? readString(beforeJson.open_in_gmail_url);
                const beforePreview = evidencePreviews[previewCacheKey(change.id, "before")] ?? null;
                const afterPreview = evidencePreviews[previewCacheKey(change.id, "after")] ?? null;

                return (
                  <article key={change.id} className="rounded-2xl border border-line bg-white p-4 shadow-card">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="space-y-1">
                        <h3 className="text-base font-semibold text-ink">{displayTitle}</h3>
                        <p className="text-sm text-muted">
                          {displayCourse} · detected {change.detected_at}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant={sourceType === "email" ? "warning" : "muted"}>{sourceType === "email" ? "EMAIL" : "CALENDAR"}</Badge>
                        <Badge variant={priorityLabel === "high" ? "warning" : "muted"}>{priorityLabel}</Badge>
                        <Badge variant={viewed ? "muted" : "warning"}>{viewed ? "Viewed" : "Unread"}</Badge>
                      </div>
                    </div>

                    <div className="mt-3 rounded-xl border border-line bg-slate-50/85 p-3">
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-600">At-a-glance Summary</p>
                      <div className="grid gap-3 lg:grid-cols-2">
                        <SummarySideCard title="Old" side={summary.old} emptyValueText="No previous value" />
                        <SummarySideCard title="New" side={summary.new} emptyValueText="Removed in latest snapshot" />
                      </div>
                    </div>

                    <details
                      className="mt-3 rounded-xl border border-line bg-white"
                      onToggle={(event) => {
                        if (isEmailChange || !event.currentTarget.open) {
                          return;
                        }
                        if (change.has_before_evidence) {
                          void onPreviewEvidence(change.id, "before");
                        }
                        if (change.has_after_evidence) {
                          void onPreviewEvidence(change.id, "after");
                        }
                      }}
                    >
                      <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-ink">Evidence and metadata</summary>
                      <div className="border-t border-line p-3 text-sm text-muted">
                        <div className="grid gap-2 md:grid-cols-2">
                          <div>change type: {change.change_type}</div>
                          <div>notification: {notificationState ?? "-"}</div>
                          {isEmailChange ? (
                            <>
                              <div>subject: {gmailSubject}</div>
                              <div>from: {gmailFrom ?? "n/a"}</div>
                              <div>internal date: {gmailInternalDate ?? "n/a"}</div>
                              <div className="md:col-span-2">snippet: {gmailSnippet ?? "n/a"}</div>
                            </>
                          ) : (
                            <>
                              <div>delta: {change.delta_seconds ?? "n/a"}</div>
                              <div>
                                before -&gt; after: {String((beforeJson.start_at_utc ?? "n/a") as string)} -&gt;{" "}
                                {String((afterJson.start_at_utc ?? "n/a") as string)}
                              </div>
                              <div className="md:col-span-2">
                                after evidence: {change.has_after_evidence ? change.after_evidence_kind ?? "available" : "n/a"}
                              </div>
                            </>
                          )}
                        </div>
                        {!isEmailChange ? (
                          <div className="mt-4 grid gap-3 lg:grid-cols-2">
                            <EvidencePreviewPanel title="Old Preview" preview={beforePreview} />
                            <EvidencePreviewPanel title="New Preview" preview={afterPreview} />
                          </div>
                        ) : null}
                      </div>
                    </details>

                    <div className="mt-3 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_auto] md:items-end">
                      <div className="space-y-2">
                        <Label htmlFor={`note-${change.id}`}>Optional note</Label>
                        <Textarea
                          id={`note-${change.id}`}
                          value={changeNotes[change.id] ?? ""}
                          onChange={(event) => onChangeNote(change.id, event.target.value)}
                          className="min-h-16"
                        />
                      </div>

                      <Button variant={viewed ? "secondary" : "default"} onClick={() => void onToggleViewed(change)}>
                        {viewed ? "Mark Unread" : "Mark Viewed"}
                      </Button>

                      {isEmailChange ? (
                        openInGmailUrl ? (
                          <Button variant="outline" asChild>
                            <a href={openInGmailUrl} target="_blank" rel="noreferrer">
                              <ExternalLink className="mr-2 h-4 w-4" />
                              Open in Gmail
                            </a>
                          </Button>
                        ) : (
                          <Button variant="outline" disabled>
                            Open in Gmail
                          </Button>
                        )
                      ) : null}
                    </div>
                  </article>
                );
              })}
            </div>
          </SectionState>
        </CardContent>
      </Card>
    </section>
  );
}

function readString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

type SummarySideCardProps = {
  title: "Old" | "New";
  side: ChangeSummarySide;
  emptyValueText: string;
};

function SummarySideCard({ title, side, emptyValueText }: SummarySideCardProps) {
  const valueText = side.value_time ? formatSummaryDate(side.value_time) : emptyValueText;
  const inputText = side.input_label ?? sourceTypeLabel(side.input_type);
  const inputBadge = sourceTypeBadge(side.input_type);
  const observedText = side.input_observed_at ? formatSummaryDate(side.input_observed_at) : "n/a";

  return (
    <div className="rounded-lg border border-line bg-white p-3">
      <p className="mb-2 text-sm font-semibold text-ink">{title}</p>
      <dl className="space-y-1 text-sm text-muted">
        <div className="grid grid-cols-[90px_1fr] gap-2">
          <dt>Value time</dt>
          <dd className="font-medium text-ink" title={side.value_time ?? undefined}>
            {valueText}
          </dd>
        </div>
        <div className="grid grid-cols-[90px_1fr] gap-2">
          <dt>Input</dt>
          <dd className="flex flex-wrap items-center gap-2 text-ink">
            <Badge variant={inputBadge.variant} title={`Input type: ${inputBadge.label}`} aria-label={`Input type: ${inputBadge.label}`}>
              {inputBadge.label}
            </Badge>
            <span>{inputText}</span>
          </dd>
        </div>
        <div className="grid grid-cols-[90px_1fr] gap-2">
          <dt>Observed at</dt>
          <dd title={side.input_observed_at ?? undefined}>{observedText}</dd>
        </div>
      </dl>
    </div>
  );
}

function sourceTypeLabel(value: "ics" | "email" | null): string {
  if (value === "email") {
    return "Email input";
  }
  if (value === "ics") {
    return "Calendar input";
  }
  return "n/a";
}

function sourceTypeBadge(value: "ics" | "email" | null): { label: "EMAIL" | "CALENDAR" | "UNKNOWN"; variant: "warning" | "muted" } {
  if (value === "email") {
    return { label: "EMAIL", variant: "warning" };
  }
  if (value === "ics") {
    return { label: "CALENDAR", variant: "muted" };
  }
  return { label: "UNKNOWN", variant: "muted" };
}

type EvidencePreviewPanelProps = {
  title: "Old Preview" | "New Preview";
  preview: EvidencePreviewState | null;
};

function EvidencePreviewPanel({ title, preview }: EvidencePreviewPanelProps) {
  return (
    <div className="rounded-lg border border-line bg-slate-50/75 p-3">
      <p className="mb-2 text-sm font-semibold text-ink">{title}</p>
      {preview?.loading ? <p className="text-xs text-muted">Loading preview...</p> : null}
      {preview?.error ? <p className="text-xs text-danger">Preview error: {preview.error}</p> : null}
      {preview?.data
        ? (() => {
            const data = preview.data;
            return (
              <div className="space-y-2">
                <p className="text-xs text-muted">
                  {data.filename}
                  {data.truncated ? " · Preview truncated" : ""}
                </p>
                {!data.events.length ? <p className="text-xs text-muted">No VEVENT entries found.</p> : null}
                <div className="max-h-72 space-y-2 overflow-auto pr-1">
                  {data.events.map((event, index) => {
                    const key = event.uid ?? `${data.side}-${index}`;
                    return (
                      <div key={key} className="rounded-md border border-line bg-white p-2 text-xs text-slate-700">
                        <p className="font-semibold text-ink">{event.summary ?? "Untitled event"}</p>
                        <dl className="mt-1 grid grid-cols-[84px_1fr] gap-x-2 gap-y-1">
                          <dt className="text-muted">UID</dt>
                          <dd className="break-all">{event.uid ?? "n/a"}</dd>
                          <dt className="text-muted">DTSTART</dt>
                          <dd>{event.dtstart ?? "n/a"}</dd>
                          <dt className="text-muted">DTEND</dt>
                          <dd>{event.dtend ?? "n/a"}</dd>
                          <dt className="text-muted">Location</dt>
                          <dd>{event.location ?? "n/a"}</dd>
                          <dt className="text-muted">Description</dt>
                          <dd className="whitespace-pre-wrap break-words">{event.description ?? "n/a"}</dd>
                        </dl>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })()
        : null}
      {!preview ? <p className="text-xs text-muted">Open evidence panel to load preview.</p> : null}
    </div>
  );
}

function previewCacheKey(changeId: number, side: "before" | "after"): string {
  return `${changeId}:${side}`;
}
