import { useMemo } from "react";
import { ExternalLink, Loader2, RefreshCw } from "lucide-react";

import { SectionState } from "@/components/dashboard/section-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  ChangeDiffViewModel,
  DiffSummaryField,
  FieldDiff,
  computeOverviewCounts,
  toChangeDiffViewModel,
} from "@/lib/event-diff";
import type { ChangeFilter } from "@/lib/hooks/use-feed-data";
import { ChangeFeedRecord } from "@/lib/types";

type DiffSectionProps = {
  changeFilter: ChangeFilter;
  onChangeFilter: (value: ChangeFilter) => void;
  changeSourceTypeFilter: "all" | "email" | "ics";
  onChangeSourceTypeFilter: (value: "all" | "email" | "ics") => void;
  changesError: string | null;
  changesLoading: boolean;
  filteredChanges: ChangeFeedRecord[];
  changeNotes: Record<number, string>;
  onChangeNote: (changeId: number, note: string) => void;
  onToggleViewed: (change: ChangeFeedRecord) => void | Promise<void>;
  onRefreshChanges: () => void | Promise<void>;
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
  onRefreshChanges,
}: DiffSectionProps) {
  const overviewCounts = useMemo(() => computeOverviewCounts(filteredChanges), [filteredChanges]);

  return (
    <section id="diff" className="section-anchor">
      <Card className="animate-in">
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle>Diff Review</CardTitle>
              <CardDescription>Review event-level diffs only: added, removed, and modified fields.</CardDescription>
            </div>
            <Button variant="secondary" onClick={() => void onRefreshChanges()} disabled={changesLoading}>
              {changesLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
              Refresh Changes
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <OverviewStatCard label="Added" value={overviewCounts.added} variant="success" />
            <OverviewStatCard label="Removed" value={overviewCounts.removed} variant="danger" />
            <OverviewStatCard label="Modified" value={overviewCounts.modified} variant="warning" />
          </div>

          <div className="sticky top-2 z-10 rounded-2xl border border-line bg-white/95 p-3 shadow-card backdrop-blur-sm">
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-[150px]">
                <p className="mb-2 text-sm font-medium text-ink">View</p>
                <Tabs value={changeFilter} onValueChange={(value) => onChangeFilter(value as ChangeFilter)}>
                  <TabsList>
                    <TabsTrigger value="all">All</TabsTrigger>
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
                const viewModel = toChangeDiffViewModel(change);
                const sourceType = normalizeSourceType(change.input_type);
                const priorityLabel = readString((change as Record<string, unknown>).priority_label) ?? (sourceType === "email" ? "high" : "normal");
                const viewed = change.viewed_at !== null;
                const beforePayload = asRecord(change.before_json);
                const afterPayload = asRecord(change.after_json);
                const openInGmailUrl =
                  readString(afterPayload?.open_in_gmail_url) ?? readString(beforePayload?.open_in_gmail_url);
                const isEmailChange = sourceType === "email";

                return (
                  <article key={change.id} className="rounded-2xl border border-line bg-white p-4 shadow-card">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="space-y-1">
                        <h3 className="text-base font-semibold text-ink">{viewModel.title}</h3>
                        <p className="text-sm text-muted">
                          {viewModel.courseLabel} · detected {change.detected_at}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant={sourceType === "email" ? "warning" : "muted"}>{sourceType === "email" ? "EMAIL" : "CALENDAR"}</Badge>
                        <ChangeTypeBadge type={viewModel.normalizedType} />
                        <Badge variant={priorityLabel === "high" ? "warning" : "muted"}>{priorityLabel}</Badge>
                        <Badge variant={viewed ? "muted" : "warning"}>{viewed ? "Viewed" : "Unread"}</Badge>
                      </div>
                    </div>

                    <div className="mt-3 rounded-xl border border-line bg-slate-50/85 p-3">
                      {viewModel.normalizedType === "created" ? (
                        <SummaryFieldList title="Added event" fields={viewModel.afterSummary} />
                      ) : null}
                      {viewModel.normalizedType === "removed" ? (
                        <SummaryFieldList title="Removed event" fields={viewModel.beforeSummary} />
                      ) : null}
                      {viewModel.normalizedType === "due_changed" ? (
                        <ModifiedFieldList fieldDiffs={viewModel.fieldDiffs} />
                      ) : null}
                    </div>

                    {isEmailChange ? (
                      <div className="mt-3 rounded-xl border border-line bg-white p-3 text-sm text-muted">
                        <p className="font-medium text-ink">Email-linked change</p>
                        <p className="mt-1">
                          Subject: {readString(afterPayload?.subject) ?? readString(beforePayload?.subject) ?? "n/a"}
                        </p>
                        <p>From: {readString(afterPayload?.from) ?? readString(beforePayload?.from) ?? "n/a"}</p>
                      </div>
                    ) : null}

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

type OverviewStatCardProps = {
  label: string;
  value: number;
  variant: "success" | "danger" | "warning";
};

function OverviewStatCard({ label, value, variant }: OverviewStatCardProps) {
  const variantClassName =
    variant === "success"
      ? "border-emerald-200 bg-emerald-50"
      : variant === "danger"
        ? "border-rose-200 bg-rose-50"
        : "border-amber-200 bg-amber-50";

  return (
    <div className={`rounded-2xl border p-4 ${variantClassName}`}>
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-600">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-ink">{value}</p>
    </div>
  );
}

type SummaryFieldListProps = {
  title: string;
  fields: DiffSummaryField[];
};

function SummaryFieldList({ title, fields }: SummaryFieldListProps) {
  return (
    <div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-600">{title}</p>
      <div className="grid gap-2 md:grid-cols-2">
        {fields.map((field) => (
          <div key={field.field} className="rounded-lg border border-line bg-white p-2">
            <p className="text-xs text-muted">{field.label}</p>
            <p className="mt-1 whitespace-pre-wrap break-words text-sm text-ink">{field.value}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

type ModifiedFieldListProps = {
  fieldDiffs: FieldDiff[];
};

function ModifiedFieldList({ fieldDiffs }: ModifiedFieldListProps) {
  if (!fieldDiffs.length) {
    return (
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-600">Modified fields</p>
        <p className="text-sm text-muted">No key-field delta captured for this record.</p>
      </div>
    );
  }

  return (
    <div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-600">Modified fields</p>
      <div className="space-y-2">
        {fieldDiffs.map((item) => (
          <div key={item.field} className="rounded-lg border border-line bg-white p-3">
            <p className="text-sm font-medium text-ink">{item.label}</p>
            <div className="mt-2 grid gap-2 md:grid-cols-2">
              <div>
                <p className="text-xs uppercase tracking-wide text-muted">Before</p>
                <p className="whitespace-pre-wrap break-words text-sm text-ink">{item.before}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-muted">After</p>
                <p className="whitespace-pre-wrap break-words text-sm text-ink">{item.after}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ChangeTypeBadge({ type }: { type: ChangeDiffViewModel["normalizedType"] }) {
  if (type === "created") {
    return <Badge variant="success">Added</Badge>;
  }
  if (type === "removed") {
    return <Badge variant="danger">Removed</Badge>;
  }
  return <Badge variant="default">Modified</Badge>;
}

function normalizeSourceType(value: unknown): "email" | "ics" {
  if (typeof value === "string" && value.trim().toLowerCase() === "email") {
    return "email";
  }
  return "ics";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function readString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}
