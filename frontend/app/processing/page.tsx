"use client";

import { useEffect } from "react";
import { Loader2, RefreshCw, Workflow } from "lucide-react";

import { DashboardPage, DashboardPageHeader } from "@/components/dashboard/page-shell";
import { ProcessingSection } from "@/components/dashboard/sections/processing-section";
import { DashboardToastStack } from "@/components/dashboard/toast-stack";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useProcessingData } from "@/lib/hooks/use-processing-data";

export default function ProcessingPage() {
  const {
    configError,
    toasts,
    needsOnboarding,
    inputs,
    activeInputId,
    inputsLoading,
    inputsError,
    handleActiveInputChange,
    handleRefreshInputs,
    runManualSync,
    handleRetryManualSyncBusy,
    manualSyncingInputId,
    manualSyncBusyInputId,
    manualSyncBusyMessage,
    manualSyncRetryAfterSeconds,
    manualSyncAutoRetried,
    health,
    healthLoading,
    healthError,
    loadHealth,
  } = useProcessingData();

  useEffect(() => {
    if (!needsOnboarding) {
      return;
    }
    window.location.replace("/ui/onboarding");
  }, [needsOnboarding]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (healthLoading) {
        return;
      }
      void loadHealth();
    }, 60_000);

    return () => {
      window.clearInterval(timer);
    };
  }, [healthLoading, loadHealth]);

  return (
    <DashboardPage>
      <DashboardPageHeader
        icon={Workflow}
        title="Processing"
        description="Manual sync control and runtime health for ICS + Gmail inputs."
        current="processing"
        activeInputId={activeInputId}
        showOnboardingNav={needsOnboarding}
      />

      {configError ? (
        <Alert>
          <AlertTitle>Configuration Missing</AlertTitle>
          <AlertDescription>{configError}</AlertDescription>
        </Alert>
      ) : null}

      <Card className="animate-in">
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base">Runtime Health</CardTitle>
              <CardDescription>Scheduler and database status from `/health`.</CardDescription>
            </div>
            <Button variant="secondary" size="sm" onClick={() => void loadHealth()} disabled={healthLoading}>
              {healthLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
              Refresh
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {healthError ? (
            <Alert>
              <AlertTitle>Health request failed</AlertTitle>
              <AlertDescription>{healthError}</AlertDescription>
            </Alert>
          ) : null}
          {!healthError && health ? (
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
              <HealthMetric label="Service" value={health.status} />
              <HealthMetric label="DB" value={health.db.ok ? "ok" : "degraded"} />
              <HealthMetric label="Scheduler" value={health.scheduler.running ? "running" : "idle"} />
              <HealthMetric label="Last Tick" value={health.scheduler.last_tick_at ?? "never"} />
              <HealthMetric label="Last Synced Inputs" value={String(health.scheduler.last_synced_inputs)} />
              <HealthMetric
                label="Next Expected Input"
                value={health.scheduler.next_expected_input_id ? `input-${health.scheduler.next_expected_input_id}` : "n/a"}
              />
            </div>
          ) : null}
          {!healthError && !health ? (
            <p className="text-muted">No health payload loaded yet.</p>
          ) : null}
        </CardContent>
      </Card>

      <ProcessingSection
        inputs={inputs}
        activeInputId={activeInputId}
        inputsLoading={inputsLoading}
        inputsError={inputsError}
        manualSyncingInputId={manualSyncingInputId}
        manualSyncBusyInputId={manualSyncBusyInputId}
        manualSyncBusyMessage={manualSyncBusyMessage}
        manualSyncRetryAfterSeconds={manualSyncRetryAfterSeconds}
        manualSyncAutoRetried={manualSyncAutoRetried}
        onActiveInputChange={handleActiveInputChange}
        onRefreshInputs={handleRefreshInputs}
        onRunManualSync={runManualSync}
        onRetryManualSyncBusy={handleRetryManualSyncBusy}
      />

      <DashboardToastStack toasts={toasts} />
    </DashboardPage>
  );
}

function HealthMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-line bg-slate-50 p-3">
      <p className="text-xs uppercase tracking-wide text-muted">{label}</p>
      <div className="mt-1 flex items-center gap-2">
        <Badge variant="muted">{value}</Badge>
      </div>
    </div>
  );
}
