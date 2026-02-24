"use client";

import { useEffect } from "react";
import { Loader2, RefreshCw, Settings2, Workflow } from "lucide-react";

import { AppNav } from "@/components/dashboard/app-nav";
import { ManagementSection } from "@/components/dashboard/sections/management-section";
import { ProcessingSection } from "@/components/dashboard/sections/processing-section";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useDashboardData } from "@/lib/hooks/use-dashboard-data";

export default function ProcessingPage() {
  const {
    configError,
    showDevTools,
    toasts,
    users,
    activeUserId,
    usersLoading,
    usersError,
    handleActiveUserChange,
    sources,
    activeSourceId,
    sourcesLoading,
    sourcesError,
    handleActiveSourceChange,
    handleRefreshSources,
    runManualSync,
    handleRetryManualSyncBusy,
    manualSyncingSourceId,
    manualSyncBusySourceId,
    manualSyncBusyMessage,
    manualSyncRetryAfterSeconds,
    manualSyncAutoRetried,
    healthError,
    healthLoading,
    scheduler,
    loadHealth,
    status,
    statusLoading,
    statusError,
    loadStatus,
    scopedError,
    scopedLoading,
    overrides,
    courseSet,
    courseOriginal,
    courseDisplay,
    setCourseOriginal,
    setCourseDisplay,
    courseBusy,
    handleSaveCourseRename,
    handleDeleteCourseRename,
    formatCourseOptionLabel,
    taskSet,
    taskUid,
    taskDisplayTitle,
    setTaskUid,
    setTaskDisplayTitle,
    taskBusy,
    handleSaveTaskRename,
    handleDeleteTaskRename,
    getTaskDisplayTitle,
  } = useDashboardData();

  const visibleInputs = activeUserId ? sources.filter((source) => source.user_id === activeUserId) : sources;
  const activeInput = activeSourceId ? visibleInputs.find((source) => source.id === activeSourceId) ?? null : null;
  const activeInputType = activeInput?.type ?? null;
  const hasStatusLoadError = Boolean(healthError || statusError);
  const overallStatusLevel = readOverallStatusLevel({
    status,
    hasStatusLoadError,
  });
  const overallStatusHeadline = readOverallStatusHeadline(overallStatusLevel);
  const statusTimestamp = status?.scheduler_last_tick_at ?? "unknown";

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (healthLoading || statusLoading) {
        return;
      }
      void loadHealth();
      void loadStatus();
    }, 60_000);

    return () => {
      window.clearInterval(timer);
    };
  }, [healthLoading, statusLoading, loadHealth, loadStatus]);

  return (
    <div className="container py-4 md:py-6">
      <div className="mx-auto max-w-6xl space-y-4 md:space-y-6">
        <header className="animate-fade-in rounded-2xl border border-line bg-white/90 p-5 shadow-card">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="inline-flex items-center gap-2 text-2xl font-semibold [font-family:var(--font-heading)] md:text-3xl">
                <Workflow className="h-6 w-6 text-accent" />
                Processing
              </h1>
              <p className="mt-1 text-sm text-muted">
                Run manual sync, inspect runtime state, and manage ICS rename overrides for the selected input.
              </p>
            </div>
            <AppNav current="processing" activeUserId={activeUserId} activeInputId={activeSourceId} showDev={showDevTools} />
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
            <CardTitle>Active User Context</CardTitle>
            <CardDescription>Processing and sync actions are scoped to the current user.</CardDescription>
          </CardHeader>
          <CardContent>
            {usersError ? (
              <Alert>
                <AlertTitle>User Load Failed</AlertTitle>
                <AlertDescription>{usersError}</AlertDescription>
              </Alert>
            ) : usersLoading ? (
              <Skeleton className="h-10" />
            ) : !users.length ? (
              <Alert>
                <AlertTitle>No User</AlertTitle>
                <AlertDescription>Initialize user settings first.</AlertDescription>
              </Alert>
            ) : (
              <div className="max-w-md space-y-2">
                <Label htmlFor="processing-user">User</Label>
                <Select
                  id="processing-user"
                  value={activeUserId ? String(activeUserId) : ""}
                  onChange={(event) => {
                    const parsed = Number(event.target.value);
                    if (Number.isInteger(parsed) && parsed > 0) {
                      void handleActiveUserChange(parsed);
                    }
                  }}
                >
                  {users.map((user) => (
                    <option key={user.id} value={String(user.id)}>
                      {user.id} - {user.name}
                    </option>
                  ))}
                </Select>
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="animate-fade-in">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle className="text-base">System Status</CardTitle>
                <CardDescription>Current automatic sync status.</CardDescription>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  void loadHealth();
                  void loadStatus();
                }}
                disabled={healthLoading || statusLoading}
              >
                {healthLoading || statusLoading ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="mr-2 h-4 w-4" />
                )}
                Refresh Status
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {healthLoading || statusLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-20" />
                <Skeleton className="h-10" />
              </div>
            ) : (
              <div className="space-y-4">
                <div className={cn("rounded-2xl border p-4", readOverallStatusPanelClass(overallStatusLevel))}>
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <Badge variant={readOverallStatusBadgeVariant(overallStatusLevel)}>{readOverallStatusLabel(overallStatusLevel)}</Badge>
                      <span className="text-sm font-medium">{overallStatusHeadline}</span>
                    </div>
                    <div className="text-xs">Last scheduler check: {statusTimestamp}</div>
                  </div>
                  {overallStatusLevel === "attention" ? (
                    <p className="mt-2 text-sm">{readOverallStatusAttentionDetail({ status, hasStatusLoadError })}</p>
                  ) : null}
                </div>

                <details className="rounded-2xl border border-line bg-white/85">
                  <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-ink">Advanced diagnostics (debug)</summary>
                  <div className="border-t border-line p-4">
                    {hasStatusLoadError ? (
                      <Alert>
                        <AlertTitle>Diagnostic data unavailable</AlertTitle>
                        <AlertDescription>{healthError ?? statusError}</AlertDescription>
                      </Alert>
                    ) : (
                      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                        <MetricCard
                          label="Scheduler Tick"
                          value={status?.scheduler_last_tick_at ?? "never"}
                          sub={`lock acquired=${String(status?.scheduler_lock_acquired ?? "unknown")}`}
                          status={status?.schema_guard_blocked ? "warning" : "success"}
                        />
                        <MetricCard
                          label="Due Inputs"
                          value={String(status?.due_inputs_count ?? 0)}
                          sub={`${status?.checked_in_last_5m_count ?? 0} checked in last 5m, ${
                            status?.pending_delayed_notifications_count ?? 0
                          } delayed notifications`}
                          status={(status?.due_inputs_count ?? 0) > 0 ? "info" : "neutral"}
                        />
                        <MetricCard
                          label="Recent Failures"
                          value={String(status?.failed_in_last_1h_count ?? 0)}
                          sub={`last run ${scheduler?.last_run_finished_at ?? "never"}`}
                          status={(status?.failed_in_last_1h_count ?? 0) > 0 ? "warning" : "success"}
                        />
                        <MetricCard
                          label="Run Counters"
                          value={`${scheduler?.cumulative_run_executed_count ?? 0} executed`}
                          sub={`${scheduler?.cumulative_run_skipped_lock_count ?? 0} lock-skipped ticks`}
                          status={scheduler?.last_skip_reason ? "warning" : "neutral"}
                        />
                      </div>
                    )}
                  </div>
                </details>
              </div>
            )}
          </CardContent>
        </Card>

        <ProcessingSection
          sources={visibleInputs}
          activeSourceId={activeSourceId}
          sourcesLoading={sourcesLoading}
          sourcesError={sourcesError}
          manualSyncingSourceId={manualSyncingSourceId}
          manualSyncBusySourceId={manualSyncBusySourceId}
          manualSyncBusyMessage={manualSyncBusyMessage}
          manualSyncRetryAfterSeconds={manualSyncRetryAfterSeconds}
          manualSyncAutoRetried={manualSyncAutoRetried}
          onActiveSourceChange={handleActiveSourceChange}
          onRefreshSources={handleRefreshSources}
          onRunManualSync={runManualSync}
          onRetryManualSyncBusy={handleRetryManualSyncBusy}
        />

        {activeInputType === "email" ? (
          <section className="section-anchor">
            <Card className="animate-fade-in">
              <CardHeader>
                <CardTitle className="inline-flex items-center gap-2">
                  <Settings2 className="h-4 w-4 text-accent" />
                  Management: Not Applicable
                </CardTitle>
                <CardDescription>Course/task rename mappings are available for ICS inputs only.</CardDescription>
              </CardHeader>
              <CardContent>
                <Alert>
                  <AlertTitle>EMAIL input selected</AlertTitle>
                  <AlertDescription>
                    Select a calendar input to manage course and task rename rules.
                  </AlertDescription>
                </Alert>
              </CardContent>
            </Card>
          </section>
        ) : (
          <ManagementSection
            scopedError={scopedError}
            scopedLoading={scopedLoading}
            overrides={overrides}
            courseSet={courseSet}
            courseOriginal={courseOriginal}
            courseDisplay={courseDisplay}
            courseBusy={courseBusy}
            onCourseOriginalChange={setCourseOriginal}
            onCourseDisplayChange={setCourseDisplay}
            onSaveCourseRename={handleSaveCourseRename}
            onDeleteCourseRename={handleDeleteCourseRename}
            formatCourseOptionLabel={formatCourseOptionLabel}
            taskSet={taskSet}
            taskUid={taskUid}
            taskDisplayTitle={taskDisplayTitle}
            taskBusy={taskBusy}
            onTaskUidChange={setTaskUid}
            onTaskDisplayTitleChange={setTaskDisplayTitle}
            onSaveTaskRename={handleSaveTaskRename}
            onDeleteTaskRename={handleDeleteTaskRename}
            getTaskDisplayTitle={getTaskDisplayTitle}
          />
        )}
      </div>

      <div className="fixed bottom-4 right-4 z-50 space-y-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={cn(
              "max-w-[420px] rounded-xl px-4 py-3 text-sm text-white shadow-xl",
              toast.tone === "success" && "bg-emerald-700",
              toast.tone === "error" && "bg-rose-700",
              toast.tone === "info" && "bg-slate-800"
            )}
          >
            {toast.message}
          </div>
        ))}
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  sub,
  status,
}: {
  label: string;
  value: string;
  sub: string;
  status: "success" | "warning" | "info" | "neutral";
}) {
  return (
    <div className="rounded-xl border border-line bg-slate-50 p-3">
      <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-wide text-muted">
        <span
          className={cn(
            "status-dot",
            status === "success" && "bg-success",
            status === "warning" && "bg-warning",
            status === "info" && "bg-accent",
            status === "neutral" && "bg-slate-400"
          )}
        />
        {label}
      </div>
      <div className="text-sm font-semibold text-ink">{value}</div>
      <div className="mt-1 text-xs text-muted">{sub}</div>
    </div>
  );
}

type OverallStatusLevel = "healthy" | "warning" | "attention";

function readOverallStatusLevel({
  status,
  hasStatusLoadError,
}: {
  status:
    | {
        schema_guard_blocked: boolean;
        failed_in_last_1h_count: number;
      }
    | null;
  hasStatusLoadError: boolean;
}): OverallStatusLevel {
  if (hasStatusLoadError || !status) {
    return "attention";
  }
  if (status.schema_guard_blocked) {
    return "attention";
  }
  if (status.failed_in_last_1h_count > 0) {
    return "warning";
  }
  return "healthy";
}

function readOverallStatusPanelClass(level: OverallStatusLevel): string {
  if (level === "attention") {
    return "border-rose-300 bg-rose-50 text-rose-900";
  }
  if (level === "warning") {
    return "border-amber-300 bg-amber-50 text-amber-900";
  }
  return "border-emerald-300 bg-emerald-50 text-emerald-900";
}

function readOverallStatusBadgeVariant(level: OverallStatusLevel): "success" | "warning" | "danger" {
  if (level === "attention") {
    return "danger";
  }
  if (level === "warning") {
    return "warning";
  }
  return "success";
}

function readOverallStatusLabel(level: OverallStatusLevel): string {
  if (level === "attention") {
    return "Attention";
  }
  if (level === "warning") {
    return "Warning";
  }
  return "Healthy";
}

function readOverallStatusHeadline(level: OverallStatusLevel): string {
  if (level === "attention") {
    return "Automatic sync needs attention.";
  }
  if (level === "warning") {
    return "Automatic sync is running with recent input failures.";
  }
  return "Automatic sync running normally.";
}

function readOverallStatusAttentionDetail({
  status,
  hasStatusLoadError,
}: {
  status:
    | {
        schema_guard_blocked: boolean;
      }
    | null;
  hasStatusLoadError: boolean;
}): string {
  if (status?.schema_guard_blocked) {
    return "Database schema is not ready; automatic sync is paused.";
  }
  if (hasStatusLoadError) {
    return "System status is temporarily unavailable.";
  }
  return "Automatic sync needs attention.";
}
