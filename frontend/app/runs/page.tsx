"use client";

import { useEffect, useState } from "react";
import { ListChecks, Loader2, RefreshCw } from "lucide-react";

import { AppNav } from "@/components/dashboard/app-nav";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SourceRun } from "@/lib/types";
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
    <div className="container py-4 md:py-6">
      <div className="mx-auto max-w-6xl space-y-4 md:space-y-6">
        <header className="animate-fade-in rounded-2xl border border-line bg-white/90 p-5 shadow-card">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="inline-flex items-center gap-2 text-2xl font-semibold [font-family:var(--font-heading)] md:text-3xl">
                <ListChecks className="h-6 w-6 text-accent" />
                Input Run History
              </h1>
              <p className="mt-1 text-sm text-muted">Inspect recent sync attempts, outcomes, and failure causes per input.</p>
            </div>
            <AppNav current="runs" activeInputId={selectedSourceId} />
          </div>
        </header>

        {configError ? (
          <Alert>
            <AlertTitle>Configuration Missing</AlertTitle>
            <AlertDescription>{configError}</AlertDescription>
          </Alert>
        ) : null}

        <Card className="animate-fade-in">
          <CardHeader>
            <CardTitle>Input Selection</CardTitle>
            <CardDescription>Select an input to view its latest sync run timeline.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {sourcesError ? (
              <Alert>
                <AlertTitle>Failed to Load Inputs</AlertTitle>
                <AlertDescription>{sourcesError}</AlertDescription>
              </Alert>
            ) : sourcesLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-10" />
                <Skeleton className="h-10" />
              </div>
            ) : !sources.length ? (
              <Alert>
                <AlertTitle>No Inputs</AlertTitle>
                <AlertDescription>Create an input in Dashboard before opening run history.</AlertDescription>
              </Alert>
            ) : (
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
                  <Select
                    id="runs-limit"
                    value={String(limit)}
                    onChange={(event) => selectLimit(Number(event.target.value) as RunLimitOption)}
                  >
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
            )}

            {sourceIdQueryError ? (
              <Alert>
                <AlertTitle>Input Query Error</AlertTitle>
                <AlertDescription>{sourceIdQueryError}</AlertDescription>
              </Alert>
            ) : null}

            {selectedSource ? (
              <div className="grid gap-3 rounded-2xl border border-line bg-slate-50 p-4 md:grid-cols-2 xl:grid-cols-3">
                <SummaryItem label="Input" value={selectedSource.display_label} />
                <SummaryItem label="Semester" value={selectedSource.term_label ?? "Global"} />
                <SummaryItem label="Interval" value={`${selectedSource.interval_minutes} min`} />
                <SummaryItem label="Last Result" value={selectedSource.last_result ?? "-"} />
                <SummaryItem label="Last Checked" value={selectedSource.last_checked_at ?? "-"} />
                <SummaryItem label="Next Check" value={selectedSource.next_check_at ?? "-"} />
                <SummaryItem label="Last Error" value={selectedSource.last_error ?? "-"} />
              </div>
            ) : !sourcesLoading && sources.length ? (
              <Alert>
                <AlertTitle>Select an Input</AlertTitle>
                <AlertDescription>Open an input from the selector to inspect run timeline details.</AlertDescription>
              </Alert>
            ) : null}
          </CardContent>
        </Card>

        <Card className="animate-fade-in">
          <CardHeader>
            <CardTitle>Recent Runs</CardTitle>
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
          <CardContent className="space-y-3">
            {!selectedSource ? (
              <Alert>
                <AlertTitle>No Input Selected</AlertTitle>
                <AlertDescription>Pick an input above to display run records.</AlertDescription>
              </Alert>
            ) : runsError ? (
              <Alert>
                <AlertTitle>Failed to Load Runs</AlertTitle>
                <AlertDescription>{runsError}</AlertDescription>
              </Alert>
            ) : runsLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-10" />
                <Skeleton className="h-10" />
                <Skeleton className="h-10" />
              </div>
            ) : !runs.length ? (
              <Alert>
                <AlertTitle>Empty Runs</AlertTitle>
                <AlertDescription>No run records found for this input yet.</AlertDescription>
              </Alert>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Started</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Changes</TableHead>
                    <TableHead>Trigger</TableHead>
                    <TableHead>Duration</TableHead>
                    <TableHead>Error</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {runs.map((run) => (
                    <TableRow key={run.id}>
                      <TableCell>{run.started_at}</TableCell>
                      <TableCell>
                        <Badge variant={readRunStatusVariant(run.status)}>{run.status}</Badge>
                      </TableCell>
                      <TableCell>{run.changes_count}</TableCell>
                      <TableCell>{run.trigger_type}</TableCell>
                      <TableCell>{formatDuration(run.duration_ms)}</TableCell>
                      <TableCell className="max-w-[320px] text-xs text-muted">{run.error_message ?? "-"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
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

function readRunStatusVariant(status: SourceRun["status"]): "success" | "warning" | "danger" | "muted" {
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
