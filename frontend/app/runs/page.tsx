"use client";

import { useEffect, useState } from "react";
import { ArrowRight, ListChecks, Loader2, RefreshCw } from "lucide-react";

import { DashboardPage, DashboardPageHeader } from "@/components/dashboard/page-shell";
import { SectionState } from "@/components/dashboard/section-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { InputRun } from "@/lib/types";
import { RunLimitOption, useSourceRunsPage } from "@/lib/hooks/use-source-runs-page";

export default function InputRunsPage() {
  const {
    configError,
    needsOnboarding,
    sources,
    sourcesLoading,
    sourcesError,
    selectedSourceId,
    selectedSource,
    sourceIdQueryError,
    selectSource,
    runs,
    runsLoading,
    runsError,
    runsLastRefreshedAt,
    limit,
    runLimitOptions,
    selectLimit,
    handleRefresh,
  } = useSourceRunsPage();
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (needsOnboarding) {
      window.location.replace("/ui/onboarding");
      return;
    }
  }, [needsOnboarding]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => {
      window.clearInterval(timer);
    };
  }, []);

  return (
    <DashboardPage>
      <DashboardPageHeader
        icon={ListChecks}
        title="Runs"
        description="Inspect recent sync attempts, outcomes, and failure causes per input."
        current="runs"
        activeInputId={selectedSourceId}
      />

      {configError ? (
        <Alert>
          <AlertTitle>Configuration Missing</AlertTitle>
          <AlertDescription>{configError}</AlertDescription>
        </Alert>
      ) : null}

      <Card className="animate-in">
        <CardHeader>
          <CardTitle>Run Filters</CardTitle>
          <CardDescription>Select an input and inspect its latest sync timeline.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <SectionState
            isLoading={sourcesLoading}
            error={sourcesError}
            isEmpty={!sourcesLoading && !sourcesError && !sources.length}
            loadingRows={2}
            errorTitle="Failed to Load Inputs"
            emptyTitle="No Inputs"
            emptyDescription="Create an input in Inputs workspace before opening run history."
          >
            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_180px_auto]">
              <div className="space-y-2">
                <Label htmlFor="runs-source">Input</Label>
                <Select
                  id="runs-source"
                  value={selectedSourceId ? String(selectedSourceId) : ""}
                  onChange={(event) => {
                    const value = event.target.value.trim();
                    if (!value) {
                      selectSource(null);
                      return;
                    }
                    selectSource(Number(value));
                  }}
                >
                  <option value="">Select an input</option>
                  {sources.map((source) => (
                    <option key={source.id} value={String(source.id)}>
                      {source.id} - {source.display_label}
                    </option>
                  ))}
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="runs-limit">Limit</Label>
                <Select id="runs-limit" value={String(limit)} onChange={(event) => selectLimit(Number(event.target.value) as RunLimitOption)}>
                  {runLimitOptions.map((option) => (
                    <option key={option} value={String(option)}>
                      {option}
                    </option>
                  ))}
                </Select>
              </div>

              <div className="flex items-end">
                <Button variant="secondary" onClick={() => void handleRefresh()} disabled={sourcesLoading}>
                  {sourcesLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
                  Refresh
                </Button>
              </div>
            </div>
          </SectionState>

          {sourceIdQueryError ? (
            <Alert>
              <AlertTitle>Input Query Error</AlertTitle>
              <AlertDescription>{sourceIdQueryError}</AlertDescription>
            </Alert>
          ) : null}

          {selectedSource ? (
            <div className="grid gap-3 rounded-2xl border border-line bg-slate-50/85 p-4 md:grid-cols-2 xl:grid-cols-4">
              <SummaryItem label="Input" value={selectedSource.display_label} />
              <SummaryItem label="Interval" value={`${selectedSource.interval_minutes} min`} />
              <SummaryItem label="Next Check" value={selectedSource.next_check_at ?? "-"} />
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card className="animate-in">
        <CardHeader>
          <CardTitle>Recent Timeline</CardTitle>
          <CardDescription>
            {selectedSource ? `Latest ${limit} runs for "${selectedSource.display_label}"` : "Select an input to load run history."}
          </CardDescription>
          {selectedSource ? (
            <div className="text-xs text-muted">
              Last refreshed:{" "}
              {runsLastRefreshedAt ? `${formatAbsoluteTimestamp(runsLastRefreshedAt)} (${formatRelativeTime(runsLastRefreshedAt, now)})` : "-"}
            </div>
          ) : null}
        </CardHeader>
        <CardContent>
          {!selectedSource ? (
            <Alert>
              <AlertTitle>No Input Selected</AlertTitle>
              <AlertDescription>Pick an input above to display run records.</AlertDescription>
            </Alert>
          ) : (
            <SectionState
              isLoading={runsLoading}
              error={runsError}
              isEmpty={!runsLoading && !runsError && runs.length === 0}
              loadingRows={3}
              errorTitle="Failed to Load Runs"
              emptyTitle="Empty Runs"
              emptyDescription="No run records found for this input yet."
            >
              <div className="stagger-fade space-y-3">
                {runs.map((run) => {
                  const statusVariant = readRunStatusVariant(run.status);
                  const hasError = Boolean(run.error_message);
                  return (
                    <article key={run.id} className="rounded-2xl border border-line bg-white p-4 shadow-card">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <Badge variant={statusVariant}>{run.status}</Badge>
                          <span className="text-sm font-medium text-ink">{run.started_at}</span>
                        </div>
                        <span className="text-xs text-muted">run-{run.id}</span>
                      </div>

                      <div className="mt-3 grid gap-2 text-sm text-muted md:grid-cols-2 xl:grid-cols-4">
                        <RunMeta label="Trigger" value={run.trigger_type} />
                        <RunMeta label="Changes" value={String(run.changes_count)} />
                        <RunMeta label="Duration" value={formatDuration(run.duration_ms)} />
                        <RunMeta label="Finished" value={run.finished_at ?? "in progress"} />
                      </div>

                      {hasError ? (
                        <details className="mt-3 rounded-xl border border-rose-200 bg-rose-50/70">
                          <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-rose-900">Error details</summary>
                          <div className="border-t border-rose-200 px-3 py-2 text-xs text-rose-900">{run.error_message}</div>
                        </details>
                      ) : (
                        <div className="mt-3 inline-flex items-center gap-1 text-xs text-muted">
                          <ArrowRight className="h-3.5 w-3.5" />
                          No error reported
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            </SectionState>
          )}
        </CardContent>
      </Card>
    </DashboardPage>
  );
}

function SummaryItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-1 text-sm font-medium text-ink">{value}</div>
    </div>
  );
}

function RunMeta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-0.5 text-sm text-ink">{value}</div>
    </div>
  );
}

function readRunStatusVariant(status: InputRun["status"]): "success" | "warning" | "danger" | "muted" {
  if (status === "CHANGED") {
    return "success";
  }
  if (status === "NO_CHANGE") {
    return "muted";
  }
  if (status === "LOCK_SKIPPED") {
    return "warning";
  }
  if (status === "FETCH_FAILED" || status === "PARSE_FAILED" || status === "DIFF_FAILED" || status === "EMAIL_FAILED") {
    return "danger";
  }
  return "muted";
}

function formatDuration(durationMs: number | null): string {
  if (durationMs === null) {
    return "-";
  }
  if (durationMs < 1000) {
    return `${durationMs} ms`;
  }
  return `${(durationMs / 1000).toFixed(1)} s`;
}

function formatAbsoluteTimestamp(date: Date): string {
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function formatRelativeTime(date: Date, nowMs: number): string {
  const diffSeconds = Math.max(0, Math.floor((nowMs - date.getTime()) / 1000));
  if (diffSeconds < 60) {
    return `${diffSeconds}s ago`;
  }

  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) {
    return `${diffMinutes}m ago`;
  }

  const diffHours = Math.floor(diffMinutes / 60);
  return `${diffHours}h ago`;
}
