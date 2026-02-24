import { ExternalLink, Loader2, RefreshCw } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { deriveChangeSummary, formatSummaryDate } from "@/lib/change-summary";
import { ChangeFeedRecord, ChangeRecord, ChangeSummarySide } from "@/lib/types";
import { ChangeFilter } from "@/lib/hooks/use-dashboard-data";

type DiffSectionProps = {
  changeFilter: ChangeFilter;
  onChangeFilter: (value: ChangeFilter) => void;
  changeSourceTypeFilter: "all" | "email" | "ics";
  onChangeSourceTypeFilter: (value: "all" | "email" | "ics") => void;
  feedTermScope: "current" | "all" | "term";
  onFeedTermScopeChange: (value: "current" | "all" | "term") => void;
  feedTermId: number | null;
  onFeedTermIdChange: (value: number | null) => void;
  activeUserTerms: Array<{ id: number; code: string; label: string }>;
  changesError: string | null;
  changesLoading: boolean;
  filteredChanges: ChangeRecord[];
  changeNotes: Record<number, string>;
  onChangeNote: (changeId: number, note: string) => void;
  onToggleViewed: (change: ChangeRecord) => void | Promise<void>;
  onDownloadEvidence: (changeId: number, side: "before" | "after") => void | Promise<void>;
  onRefreshChanges: () => void | Promise<void>;
  getTaskDisplayTitle: (uid: string, title: string) => string;
  getCourseDisplayLabel: (label: string) => string;
};

export function DiffSection({
  changeFilter,
  onChangeFilter,
  changeSourceTypeFilter,
  onChangeSourceTypeFilter,
  feedTermScope,
  onFeedTermScopeChange,
  feedTermId,
  onFeedTermIdChange,
  activeUserTerms,
  changesError,
  changesLoading,
  filteredChanges,
  changeNotes,
  onChangeNote,
  onToggleViewed,
  onDownloadEvidence,
  onRefreshChanges,
  getTaskDisplayTitle,
  getCourseDisplayLabel,
}: DiffSectionProps) {
  return (
    <section id="diff" className="section-anchor">
      <Card className="animate-fade-in">
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle>Notification Layer: Diff Review</CardTitle>
              <CardDescription>Review change records, toggle viewed state, and download evidence files.</CardDescription>
            </div>
            <Button variant="secondary" onClick={() => void onRefreshChanges()} disabled={changesLoading}>
              {changesLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
              Refresh Changes
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <Tabs value={changeFilter} onValueChange={(value) => onChangeFilter(value as ChangeFilter)}>
              <TabsList>
                <TabsTrigger value="all">All</TabsTrigger>
                <TabsTrigger value="unread">Unread</TabsTrigger>
              </TabsList>
            </Tabs>
            <div className="ml-auto flex items-center gap-2 text-sm">
              <Label htmlFor="change-source-type">Input Type</Label>
              <select
                id="change-source-type"
                className="h-9 rounded-md border border-line bg-white px-2 py-1 text-sm"
                value={changeSourceTypeFilter}
                onChange={(event) => onChangeSourceTypeFilter(event.target.value as "all" | "email" | "ics")}
              >
                <option value="all">All Inputs</option>
                <option value="email">Email Only</option>
                <option value="ics">Calendar Only</option>
              </select>
            </div>
            <div className="flex items-center gap-2 text-sm">
              <Label htmlFor="change-term-scope">Term</Label>
              <select
                id="change-term-scope"
                className="h-9 rounded-md border border-line bg-white px-2 py-1 text-sm"
                value={feedTermScope}
                onChange={(event) => onFeedTermScopeChange(event.target.value as "current" | "all" | "term")}
              >
                <option value="current">Current + Global Email</option>
                <option value="all">All Terms</option>
                <option value="term">Specific Term</option>
              </select>
            </div>
            {feedTermScope === "term" ? (
              <div className="flex items-center gap-2 text-sm">
                <Label htmlFor="change-term-id">Semester</Label>
                <select
                  id="change-term-id"
                  className="h-9 rounded-md border border-line bg-white px-2 py-1 text-sm"
                  value={feedTermId ? String(feedTermId) : ""}
                  onChange={(event) => {
                    const value = event.target.value.trim();
                    if (!value) {
                      onFeedTermIdChange(null);
                      return;
                    }
                    onFeedTermIdChange(Number(value));
                  }}
                >
                  <option value="">Select term</option>
                  {activeUserTerms.map((term) => (
                    <option key={term.id} value={String(term.id)}>
                      {term.label} ({term.code})
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
          </div>

          {changesError ? (
            <Alert>
              <AlertTitle>Change List Failed</AlertTitle>
              <AlertDescription>{changesError}</AlertDescription>
            </Alert>
          ) : changesLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-28" />
              <Skeleton className="h-28" />
            </div>
          ) : !filteredChanges.length ? (
            <Alert>
              <AlertTitle>Empty Changes</AlertTitle>
              <AlertDescription>No changes for selected input and filter.</AlertDescription>
            </Alert>
          ) : (
            <div className="space-y-3">
              {filteredChanges.map((change) => {
                const beforeJson = change.before_json ?? {};
                const afterJson = change.after_json ?? {};
                const rawTitle = String((afterJson.title ?? beforeJson.title ?? change.event_uid) as string);
                const rawCourse = String((afterJson.course_label ?? beforeJson.course_label ?? "Unknown") as string);
                const summary = deriveChangeSummary(change as ChangeFeedRecord);
                const displayTitle = getTaskDisplayTitle(change.event_uid, rawTitle);
                const displayCourse = getCourseDisplayLabel(rawCourse);
                const viewed = change.viewed_at !== null;
                const beforePath = readEvidencePath(change.before_raw_evidence_key);
                const afterPath = readEvidencePath(change.after_raw_evidence_key);
                const sourceType = readString((change as Record<string, unknown>).input_type) ?? "ics";
                const priorityLabel = readString((change as Record<string, unknown>).priority_label) ?? (sourceType === "email" ? "high" : "normal");
                const termLabel = readString((change as Record<string, unknown>).term_label);
                const termScope = readString((change as Record<string, unknown>).term_scope) ?? "global";
                const notificationState = readString((change as Record<string, unknown>).notification_state);
                const gmailMessageId = readString(afterJson.gmail_message_id) ?? readString(beforeJson.gmail_message_id);
                const isEmailChange = gmailMessageId !== null;
                const gmailSubject = readString(afterJson.subject) ?? readString(beforeJson.subject) ?? displayTitle;
                const gmailSnippet = readString(afterJson.snippet) ?? readString(beforeJson.snippet);
                const gmailInternalDate = readString(afterJson.internal_date) ?? readString(beforeJson.internal_date);
                const gmailFrom = readString(afterJson.from) ?? readString(beforeJson.from);
                const openInGmailUrl = readString(afterJson.open_in_gmail_url) ?? readString(beforeJson.open_in_gmail_url);

                return (
                  <article key={change.id} className="rounded-2xl border border-line bg-white p-4 shadow-card">
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                      <h3 className="text-base font-semibold text-ink">{displayTitle}</h3>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant={sourceType === "email" ? "warning" : "muted"}>
                          {sourceType === "email" ? "EMAIL High Priority" : "Calendar"}
                        </Badge>
                        <Badge variant={priorityLabel === "high" ? "warning" : "muted"}>{priorityLabel}</Badge>
                        <Badge variant={viewed ? "muted" : "warning"}>{viewed ? "Viewed" : "Unread"}</Badge>
                      </div>
                    </div>

                    <div className="mb-3 rounded-xl border border-line bg-slate-50/80 p-3">
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-600">At-a-glance Summary</p>
                      <div className="grid gap-3 md:grid-cols-2">
                        <SummarySideCard title="Old" side={summary.old} emptyValueText="No previous value" />
                        <SummarySideCard title="New" side={summary.new} emptyValueText="Removed in latest snapshot" />
                      </div>
                    </div>

                    <div className="grid gap-2 text-sm text-muted md:grid-cols-2">
                      <div>term: {termScope === "global" ? "Global" : (termLabel ?? "-")}</div>
                      <div>course: {displayCourse}</div>
                      <div>type: {change.change_type}</div>
                      <div>notification: {notificationState ?? "-"}</div>
                      <div>detected_at: {change.detected_at}</div>
                      {isEmailChange ? (
                        <>
                          <div>subject: {gmailSubject}</div>
                          <div>from: {gmailFrom ?? "n/a"}</div>
                          <div>internal_date: {gmailInternalDate ?? "n/a"}</div>
                          <div className="md:col-span-2">snippet: {gmailSnippet ?? "n/a"}</div>
                        </>
                      ) : (
                        <>
                          <div>delta: {change.delta_seconds ?? "n/a"}</div>
                          <div>
                            before -&gt; after: {String((beforeJson.start_at_utc ?? "n/a") as string)} -&gt;{" "}
                            {String((afterJson.start_at_utc ?? "n/a") as string)}
                          </div>
                          <div>after evidence: {afterPath ?? "n/a"}</div>
                        </>
                      )}
                    </div>

                    <div className="mt-3 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_auto_auto] md:items-end">
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
                      ) : (
                        <>
                          <Button variant="outline" disabled={!beforePath} onClick={() => void onDownloadEvidence(change.id, "before")}>
                            Download Before ICS
                          </Button>
                          <Button variant="outline" disabled={!afterPath} onClick={() => void onDownloadEvidence(change.id, "after")}>
                            Download After ICS
                          </Button>
                        </>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          )}
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

function readEvidencePath(raw: Record<string, unknown> | null): string | null {
  if (!raw) {
    return null;
  }
  const value = raw.path;
  return typeof value === "string" && value ? value : null;
}

type SummarySideCardProps = {
  title: "Old" | "New";
  side: ChangeSummarySide;
  emptyValueText: string;
};

function SummarySideCard({ title, side, emptyValueText }: SummarySideCardProps) {
  const valueText = side.value_time ? formatSummaryDate(side.value_time) : emptyValueText;
  const sourceText = side.source_label ?? sourceTypeLabel(side.source_type);
  const sourceBadge = sourceTypeBadge(side.source_type);
  const observedText = side.source_observed_at ? formatSummaryDate(side.source_observed_at) : "n/a";

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
          <dt>Source</dt>
          <dd className="flex flex-wrap items-center gap-2 text-ink">
            <Badge
              variant={sourceBadge.variant}
              title={`Source type: ${sourceBadge.label}`}
              aria-label={`Source type: ${sourceBadge.label}`}
            >
              {sourceBadge.label}
            </Badge>
            <span>{sourceText}</span>
          </dd>
        </div>
        <div className="grid grid-cols-[90px_1fr] gap-2">
          <dt>Observed at</dt>
          <dd title={side.source_observed_at ?? undefined}>{observedText}</dd>
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
