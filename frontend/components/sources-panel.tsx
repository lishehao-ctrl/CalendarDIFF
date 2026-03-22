"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArchiveRestore, CalendarSync, ChevronRight, Mailbox, RefreshCw, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { SourceSyncProgress } from "@/components/source-sync-progress";
import { startOnboardingGmailOAuth } from "@/lib/api/onboarding";
import { createOAuthSession, createSyncRequest, deleteSource as deleteSourceRequest, getSyncRequest, listSources, sourceListCacheKey, updateSource } from "@/lib/api/sources";
import { withBasePath } from "@/lib/demo-mode";
import { useApiResource } from "@/lib/use-api-resource";
import { useSourceObservabilityMap } from "@/lib/use-source-observability-map";
import { formatDateTime, formatStatusLabel } from "@/lib/presenters";
import type { SourceObservabilityResponse, SourceRecovery, SourceRow, SyncStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const oauthQueryKeys = ["oauth_provider", "oauth_status", "source_id", "request_id", "message"] as const;

type Banner = {
  tone: "info" | "error";
  text: string;
} | null;

function sourceNeedsAttention(source: SourceRow) {
  return Boolean(source.last_error_message) || source.runtime_state === "rebind_pending" || source.config_state === "rebind_pending" || source.oauth_connection_status === "not_connected";
}

function syncTone(value: string | undefined) {
  if (!value) return "default";
  if (["queued", "running", "pending", "rebind_pending"].includes(value)) return "pending";
  if (["succeeded", "success"].includes(value)) return "approved";
  if (["failed", "error"].includes(value)) return "error";
  return "default";
}

function buildSourceInsight(source: SourceRow) {
  if (sourceNeedsAttention(source)) {
    return {
      title: source.provider === "gmail" ? "Reconnect Gmail" : "Repair this source",
      detail: "New changes from this source are not trustworthy yet.",
    };
  }

  if (source.sync_progress) {
    return {
      title: source.sync_progress.label || "Sync is in progress",
      detail: null,
    };
  }

  return {
    title: "No action needed",
    detail: null,
  };
}

function formatSourceTitle(source: SourceRow) {
  if (source.provider === "ics") return "Canvas ICS";
  return source.display_name || source.source_key;
}

function formatSourceSubtitle(source: SourceRow) {
  if (source.provider === "ics") {
    return "Student calendar feed";
  }
  return source.oauth_account_email || `${formatStatusLabel(source.source_kind, "Email")} · ${source.source_key}`;
}

function productPhaseLabel(phase: SourceRow["source_product_phase"] | SourceObservabilityResponse["source_product_phase"]) {
  switch (phase) {
    case "importing_baseline":
      return "Baseline import";
    case "needs_initial_review":
      return "Initial Review";
    case "monitoring_live":
      return "Monitoring live";
    case "needs_attention":
      return "Attention required";
    default:
      return "Phase unavailable";
  }
}

function trustStateLabel(trustState: SourceRecovery["trust_state"] | null | undefined) {
  switch (trustState) {
    case "trusted":
      return "Trusted";
    case "stale":
      return "Stale";
    case "partial":
      return "Partially trusted";
    case "blocked":
      return "Blocked";
    default:
      return "Trust unavailable";
  }
}

function trustStateTone(trustState: SourceRecovery["trust_state"] | null | undefined) {
  switch (trustState) {
    case "trusted":
      return "approved";
    case "stale":
      return "info";
    case "partial":
      return "pending";
    case "blocked":
      return "error";
    default:
      return "info";
  }
}

function resolveProductPhase(source: SourceRow, observability: SourceObservabilityResponse | undefined) {
  return observability?.source_product_phase || source.source_product_phase || null;
}

function resolveRecovery(source: SourceRow, observability: SourceObservabilityResponse | undefined) {
  return observability?.source_recovery || source.source_recovery || null;
}

function sourceSetupHref(basePath: string, provider: string) {
  if (provider === "ics") return withBasePath(basePath, "/sources/connect/canvas-ics");
  if (provider === "gmail") return withBasePath(basePath, "/sources/connect/gmail");
  return withBasePath(basePath, "/sources");
}

function ConnectSourceCard({
  provider,
  title,
  detail,
  connected,
  attention,
  href,
  icon,
  iconShellClassName,
}: {
  provider: string;
  title: string;
  detail: string;
  connected: boolean;
  attention: boolean;
  href: string;
  icon: React.ReactNode;
  iconShellClassName: string;
}) {
  return (
    <div className="rounded-[1.1rem] border border-line/80 bg-white/72 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className={cn(iconShellClassName, "h-10 w-10 rounded-[1rem]")}>{icon}</div>
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{provider}</p>
            <h3 className="mt-1 text-sm font-semibold text-ink">{title}</h3>
            <p className="mt-1 text-xs text-[#596270]">{detail}</p>
          </div>
        </div>
        <Badge tone={attention ? "pending" : connected ? "approved" : "info"}>
          {attention ? "Attention" : connected ? "Connected" : "Not connected"}
        </Badge>
      </div>
      <div className="mt-4">
        <Button asChild size="sm" variant={connected ? "ghost" : "secondary"}>
          <Link href={href}>
            {connected ? "Manage" : "Connect"}
            <ChevronRight className="ml-2 h-4 w-4" />
          </Link>
        </Button>
      </div>
    </div>
  );
}

function ConnectedSourceCard({
  source,
  observability,
  syncLabel,
  onSync,
  onDelete,
  busyDelete,
  basePath,
}: {
  source: SourceRow;
  observability: SourceObservabilityResponse | undefined;
  syncLabel?: string;
  onSync: (sourceId: number) => void;
  onDelete: (sourceId: number, provider: string) => void;
  busyDelete: number | null;
  basePath: string;
}) {
  const recovery = resolveRecovery(source, observability);
  const productPhase = resolveProductPhase(source, observability);
  const bootstrapSummary = observability?.bootstrap_summary || null;
  const needsAttention = recovery ? recovery.trust_state !== "trusted" : sourceNeedsAttention(source);
  const detailHref = withBasePath(basePath, `/sources/${source.source_id}`);
  const showSyncBadge = Boolean(syncLabel && syncLabel.toLowerCase() !== "idle");
  const showBootstrapSummary =
    Boolean(bootstrapSummary) &&
    (productPhase !== "monitoring_live" ||
      (bootstrapSummary?.review_required_count || 0) > 0 ||
      (bootstrapSummary?.conflict_count || 0) > 0);
  const secondaryTimestamp = recovery?.degraded_since
    ? `Last good sync ${formatDateTime(recovery.last_good_sync_at, "Not recorded")} · Degraded since ${formatDateTime(recovery.degraded_since)}`
    : recovery?.last_good_sync_at
      ? `Last good sync ${formatDateTime(recovery.last_good_sync_at)}`
      : `Updated ${formatDateTime(source.last_polled_at, "Never")}`;
  const primaryAction =
    recovery?.next_action === "reconnect_gmail" ? (
      <Button asChild className="w-full justify-center">
        <Link href={sourceSetupHref(basePath, source.provider)}>Reconnect Gmail</Link>
      </Button>
    ) : recovery?.next_action === "update_ics" ? (
      <Button asChild className="w-full justify-center">
        <Link href={sourceSetupHref(basePath, source.provider)}>Update Canvas ICS</Link>
      </Button>
    ) : recovery?.next_action === "retry_sync" ? (
      <Button onClick={() => onSync(source.source_id)} className="w-full justify-center">
        <RefreshCw className="mr-2 h-4 w-4" />
        {recovery.next_action_label || "Retry sync"}
      </Button>
    ) : productPhase === "needs_initial_review" ? (
      <Button asChild className="w-full justify-center">
        <Link href={withBasePath(basePath, "/initial-review")}>Open Initial Review</Link>
      </Button>
    ) : (
      <Button asChild className="w-full justify-center">
        <Link href={detailHref}>Open details</Link>
      </Button>
    );

  return (
    <Card className={needsAttention ? "animate-surface-enter interactive-lift border-[rgba(215,90,45,0.28)] bg-white p-5" : "animate-surface-enter interactive-lift bg-white p-5"}>
      <div className="min-w-0">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-base font-semibold text-ink">{formatSourceTitle(source)}</h3>
                <Badge tone="info">{productPhaseLabel(productPhase)}</Badge>
                <Badge tone={trustStateTone(recovery?.trust_state)}>{trustStateLabel(recovery?.trust_state)}</Badge>
                {showSyncBadge ? <Badge tone={syncTone(syncLabel)}>{formatStatusLabel(syncLabel, "Idle")}</Badge> : null}
              </div>
              <p className="mt-2 text-sm text-[#596270]">{formatSourceSubtitle(source)}</p>
            </div>
            <div className="grid w-full shrink-0 gap-2 sm:grid-cols-2 lg:w-[340px]">
              {primaryAction}
              <Button asChild variant="ghost" className="w-full justify-center">
                <Link href={detailHref}>Open details</Link>
              </Button>
              <div className="hidden sm:block" />
              <Button variant="ghost" className="w-full justify-center" onClick={() => onDelete(source.source_id, source.provider)} disabled={busyDelete === source.source_id}>
                <Trash2 className="mr-2 h-4 w-4" />
                {busyDelete === source.source_id ? "Archiving..." : "Archive"}
              </Button>
            </div>
          </div>

          <div className="rounded-[1rem] border border-line/80 bg-white/75 p-4 text-sm text-[#314051]">
            <p className="font-medium text-ink">{recovery?.impact_summary || buildSourceInsight(source).title}</p>
            {recovery?.next_action_label ? (
              <p className="mt-2 text-[#596270]">
                Next step: {recovery.next_action_label}
              </p>
            ) : recovery?.impact_summary ? null : buildSourceInsight(source).detail ? (
              <p className="mt-2 text-[#596270]">{buildSourceInsight(source).detail}</p>
            ) : null}
            {showBootstrapSummary && bootstrapSummary ? (
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <p>Imported: {bootstrapSummary.imported_count}</p>
                <p>Needs review: {bootstrapSummary.review_required_count}</p>
                <p>Ignored: {bootstrapSummary.ignored_count}</p>
                <p>Conflicts: {bootstrapSummary.conflict_count}</p>
              </div>
            ) : null}
          </div>

          <p className="text-xs leading-5 text-[#6d7885]">{secondaryTimestamp}</p>

          {source.sync_progress ? <SourceSyncProgress className="mt-1" progress={source.sync_progress} /> : null}
        </div>
      </div>
    </Card>
  );
}

function ArchivedSourceCard({
  source,
  onReactivate,
  busyReactivate,
  basePath,
}: {
  source: SourceRow;
  onReactivate: (sourceId: number) => void;
  busyReactivate: number | null;
  basePath: string;
}) {
  return (
    <Card className="animate-surface-enter interactive-lift bg-white/80 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-medium text-ink">{formatSourceTitle(source)}</p>
          <p className="mt-1 text-sm text-[#596270]">{formatSourceSubtitle(source)}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => onReactivate(source.source_id)} disabled={busyReactivate === source.source_id}>
            <ArchiveRestore className="mr-2 h-4 w-4" />
            {busyReactivate === source.source_id ? "Reactivating..." : "Reactivate"}
          </Button>
          <Button asChild variant="ghost">
            <Link href={withBasePath(basePath, `/sources/${source.source_id}`)}>Open details</Link>
          </Button>
        </div>
      </div>
    </Card>
  );
}

export function SourcesPanel({ basePath = "" }: { basePath?: string }) {
  const active = useApiResource<SourceRow[]>(() => listSources({ status: "active" }), [], null, {
    cacheKey: sourceListCacheKey("active"),
  });
  const archived = useApiResource<SourceRow[]>(() => listSources({ status: "archived" }), [], null, {
    cacheKey: sourceListCacheKey("archived"),
  });
  const [syncState, setSyncState] = useState<Record<number, string>>({});
  const [syncDetails, setSyncDetails] = useState<Record<number, SyncStatus | undefined>>({});
  const [busyDelete, setBusyDelete] = useState<number | null>(null);
  const [busyReactivate, setBusyReactivate] = useState<number | null>(null);
  const [banner, setBanner] = useState<Banner>(null);
  const oauthQueryHandled = useRef(false);

  const activeSources = useMemo(
    () =>
      ((active.data || []).filter((source) => source.is_active)).map((source) => {
        const detail = syncDetails[source.source_id];
        if (!detail) {
          return source;
        }
        const normalizedStatus = detail.status.toLowerCase();
        const syncStateValue =
          normalizedStatus === "running"
            ? "running"
            : normalizedStatus === "queued" || normalizedStatus === "pending"
              ? "queued"
              : source.sync_state;
        return {
          ...source,
          sync_state: syncStateValue,
          runtime_state:
            syncStateValue === "running" || syncStateValue === "queued"
              ? syncStateValue
              : source.runtime_state,
          sync_progress: detail.progress || source.sync_progress,
          last_error_code: detail.error_code ?? source.last_error_code,
          last_error_message:
            detail.error_message ?? detail.connector_result?.error_message ?? source.last_error_message,
        };
      }),
    [active.data, syncDetails],
  );
  const archivedSources = useMemo(() => (archived.data || []).filter((source) => !source.is_active), [archived.data]);
  const activeProviders = useMemo(() => new Set(activeSources.map((source) => source.provider)), [activeSources]);
  const observabilityMap = useSourceObservabilityMap(activeSources);
  const attentionSources = useMemo(
    () => activeSources.filter((source) => {
      const recovery = resolveRecovery(source, observabilityMap.data[source.source_id]);
      return recovery ? recovery.trust_state !== "trusted" : sourceNeedsAttention(source);
    }),
    [activeSources, observabilityMap.data],
  );
  const healthySources = useMemo(
    () => activeSources.filter((source) => {
      const recovery = resolveRecovery(source, observabilityMap.data[source.source_id]);
      return recovery ? recovery.trust_state === "trusted" : !sourceNeedsAttention(source);
    }),
    [activeSources, observabilityMap.data],
  );
  const initialReviewReady = useMemo(
    () =>
      activeSources.filter(
        (source) => resolveProductPhase(source, observabilityMap.data[source.source_id]) === "needs_initial_review",
      ),
    [activeSources, observabilityMap.data],
  );
  const baselineRunning = useMemo(
    () =>
      activeSources.filter(
        (source) => resolveProductPhase(source, observabilityMap.data[source.source_id]) === "importing_baseline",
      ),
    [activeSources, observabilityMap.data],
  );
  const activeRequestPairs = useMemo(
    () =>
      ((active.data || []) as SourceRow[])
        .filter((source) => source.is_active && source.active_request_id)
        .map((source) => ({ sourceId: source.source_id, requestId: source.active_request_id as string })),
    [active.data],
  );
  const activeRequestPairsKey = useMemo(
    () => activeRequestPairs.map((pair) => `${pair.sourceId}:${pair.requestId}`).sort().join("|"),
    [activeRequestPairs],
  );
  const refreshAll = useCallback(async (options?: { background?: boolean }) => {
    await Promise.all([active.refresh(options), archived.refresh(options)]);
  }, [active, archived]);

  useEffect(() => {
    let cancelled = false;
    if (activeRequestPairs.length === 0) {
      setSyncDetails((current) => (Object.keys(current).length === 0 ? current : {}));
      return;
    }

    async function poll() {
      try {
        const rows = await Promise.all(
          activeRequestPairs.map(async ({ sourceId, requestId }) => ({
            sourceId,
            payload: await getSyncRequest(requestId),
          })),
        );
        if (cancelled) return;
        const next: Record<number, SyncStatus | undefined> = {};
        const nextSyncState: Record<number, string> = {};
        let sawTerminal = false;
        for (const row of rows) {
          next[row.sourceId] = row.payload;
          nextSyncState[row.sourceId] = row.payload.status.toLowerCase();
          if (row.payload.status === "SUCCEEDED" || row.payload.status === "FAILED") {
            sawTerminal = true;
          }
        }
        setSyncDetails(next);
        setSyncState((prev) => ({ ...prev, ...nextSyncState }));
        if (sawTerminal) {
          void refreshAll({ background: true });
        }
      } catch {
        if (!cancelled) {
          return;
        }
      }
    }

    void poll();
    const intervalId = window.setInterval(() => {
      void poll();
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [activeRequestPairs, activeRequestPairsKey, refreshAll]);

  const pollSyncRequest = useCallback(
    async (sourceId: number, requestId: string, options?: { successMessage?: string; failurePrefix?: string }) => {
      setSyncState((prev) => ({ ...prev, [sourceId]: "queued" }));
      for (let attempt = 0; attempt < 15; attempt += 1) {
        const status = await getSyncRequest(requestId);
        const normalized = status.status.toLowerCase();
        setSyncState((prev) => ({ ...prev, [sourceId]: normalized }));
        if (status.status === "SUCCEEDED" || status.status === "FAILED") {
          if (status.status === "SUCCEEDED") {
            setBanner({ tone: "info", text: options?.successMessage || `Source #${sourceId} sync succeeded.` });
          } else {
            const failure = status.error_message || status.connector_result?.error_message || options?.failurePrefix || `Source #${sourceId} sync failed.`;
            setBanner({ tone: "error", text: failure });
          }
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      await refreshAll({ background: true });
    },
    [refreshAll],
  );

  useEffect(() => {
    if (oauthQueryHandled.current) return;
    oauthQueryHandled.current = true;

    const url = new URL(window.location.href);
    const provider = url.searchParams.get("oauth_provider");
    const status = url.searchParams.get("oauth_status");
    const sourceIdRaw = url.searchParams.get("source_id");
    const requestId = url.searchParams.get("request_id");
    const message = url.searchParams.get("message");

    if (!provider || provider !== "gmail" || !status) return;

    const sourceId = sourceIdRaw ? Number(sourceIdRaw) : null;
    setBanner({
      tone: status === "success" ? "info" : "error",
      text: message || (status === "success" ? "Gmail connection succeeded." : "Gmail connection failed."),
    });

    for (const key of oauthQueryKeys) {
      url.searchParams.delete(key);
    }
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);

    void refreshAll({ background: true });
    if (status === "success" && requestId && sourceId) {
      void pollSyncRequest(sourceId, requestId, {
        successMessage: "Gmail initial sync succeeded.",
        failurePrefix: "Gmail initial sync failed",
      });
    }
  }, [pollSyncRequest, refreshAll]);

  async function triggerSync(sourceId: number) {
    setBanner(null);
    try {
      const created = await createSyncRequest(sourceId, { metadata: { kind: "ui_manual_sync" } });
      await pollSyncRequest(sourceId, created.request_id);
    } catch (err) {
      const text = err instanceof Error ? err.message : "Sync failed";
      setSyncState((prev) => ({ ...prev, [sourceId]: "failed" }));
      setBanner({ tone: "error", text });
    }
  }

  async function archiveSource(sourceId: number, provider: string) {
    const confirmed = window.confirm(
      provider === "gmail"
        ? "Disconnect this Gmail mailbox and move it to Archived Sources?"
        : provider === "ics"
          ? "Archive this Canvas ICS link?"
          : "Archive this source?",
    );
    if (!confirmed) return;

    setBusyDelete(sourceId);
    setBanner(null);
    try {
      await deleteSourceRequest(sourceId);
      setBanner({
        tone: "info",
        text: provider === "gmail" ? "Mailbox disconnected and archived." : provider === "ics" ? "Canvas ICS link archived." : "Source archived.",
      });
      await refreshAll({ background: true });
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to archive source" });
    } finally {
      setBusyDelete(null);
    }
  }

  async function reactivateSource(sourceId: number) {
    setBusyReactivate(sourceId);
    setBanner(null);
    try {
      await updateSource(sourceId, { is_active: true });
      setBanner({ tone: "info", text: `Source #${sourceId} reactivated.` });
      await refreshAll({ background: true });
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to reactivate source" });
    } finally {
      setBusyReactivate(null);
    }
  }

  async function startGmailConnect() {
    const source = activeSources.find((row) => row.provider === "gmail") || archivedSources.find((row) => row.provider === "gmail") || null;
    setBanner(null);
    try {
      const session = source
        ? await createOAuthSession(source.source_id, { provider: "gmail" })
        : await startOnboardingGmailOAuth({ label_id: "INBOX", return_to: "sources" });
      window.location.assign(session.authorization_url);
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to start Gmail OAuth" });
    }
  }

  if ((active.loading && !active.data) || (archived.loading && !archived.data)) return <LoadingState label="sources" />;
  if (active.error) return <ErrorState message={active.error} />;
  if (archived.error) return <ErrorState message={archived.error} />;
  if (observabilityMap.error) return <ErrorState message={observabilityMap.error} />;

  return (
    <div className="space-y-5">
      <Card className="animate-surface-enter relative overflow-hidden p-6 md:p-7">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.13),transparent_36%),radial-gradient(circle_at_84%_20%,rgba(215,90,45,0.11),transparent_24%)]" />
        <div className="relative space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-3xl">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Sources</p>
              <h2 className="mt-3 text-3xl font-semibold text-ink">Keep intake trustworthy.</h2>
              <p className="mt-3 text-sm text-[#596270]">Fix attention first.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge tone={attentionSources.length > 0 ? "pending" : "approved"}>{attentionSources.length} attention</Badge>
              <Badge tone="info">{activeSources.length} connected</Badge>
              <Badge tone="info">{archivedSources.length} archived</Badge>
            </div>
          </div>
        </div>
      </Card>

      {banner ? (
        <Card className={banner.tone === "error" ? "border-[#efc4b5] bg-[#fff3ef] p-4" : "border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] p-4"}>
          <p className="text-sm text-[#314051]">{banner.text}</p>
        </Card>
      ) : null}

      {initialReviewReady.length > 0 ? (
        <Card className="animate-surface-enter border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] p-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Initial Review</p>
              <p className="mt-1 text-sm font-medium text-ink">
                {initialReviewReady.length === 1 ? "A source finished its first baseline import." : `${initialReviewReady.length} sources finished their first baseline import.`}
              </p>
            </div>
            <Button asChild size="sm">
              <Link href={withBasePath(basePath, "/initial-review")}>Open Initial Review</Link>
            </Button>
          </div>
        </Card>
      ) : null}

      {initialReviewReady.length === 0 && baselineRunning.length > 0 ? (
        <Card className="animate-surface-enter border border-line/80 bg-white/80 p-4">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Baseline import</p>
          <p className="mt-1 text-sm font-medium text-ink">
            {baselineRunning.length === 1 ? "A source is still building its first baseline." : `${baselineRunning.length} sources are still building their first baseline.`}
          </p>
        </Card>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.05fr)_minmax(360px,0.95fr)]">
        <div className="space-y-4">
          <Card className="animate-surface-enter animate-surface-delay-1 p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Connected sources</p>
                <h3 className="mt-1 text-lg font-semibold text-ink">Current intake</h3>
              </div>
              <Badge tone="info">{activeSources.length}</Badge>
            </div>

            <div className="mt-4 space-y-3">
              {activeSources.length === 0 ? (
                <EmptyState title="No connected sources" description="Connect Canvas ICS or Gmail to start intake." />
              ) : (
                <>
                  {attentionSources.length > 0 ? (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-xs uppercase tracking-[0.18em] text-ember">Needs attention</p>
                        <Badge tone="pending">{attentionSources.length}</Badge>
                      </div>
                      {attentionSources.map((source) => (
                        <ConnectedSourceCard
                          key={source.source_id}
                          source={source}
                          observability={observabilityMap.data[source.source_id]}
                          syncLabel={
                            syncState[source.source_id] ||
                            (source.sync_state !== "idle" ? source.sync_state : undefined) ||
                            (source.config_state === "rebind_pending" ? "rebind_pending" : undefined)
                          }
                          onSync={triggerSync}
                          onDelete={archiveSource}
                          busyDelete={busyDelete}
                          basePath={basePath}
                        />
                      ))}
                    </div>
                  ) : null}

                  {healthySources.length > 0 ? (
                    <div className={`${attentionSources.length > 0 ? "border-t border-line/80 pt-4" : ""} space-y-3`}>
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Healthy</p>
                        <Badge tone="approved">{healthySources.length}</Badge>
                      </div>
                      {healthySources.map((source) => (
                        <ConnectedSourceCard
                          key={source.source_id}
                          source={source}
                          observability={observabilityMap.data[source.source_id]}
                          syncLabel={
                            syncState[source.source_id] ||
                            (source.sync_state !== "idle" ? source.sync_state : undefined) ||
                            (source.config_state === "rebind_pending" ? "rebind_pending" : undefined)
                          }
                          onSync={triggerSync}
                          onDelete={archiveSource}
                          busyDelete={busyDelete}
                          basePath={basePath}
                        />
                      ))}
                    </div>
                  ) : null}
                </>
              )}
            </div>
          </Card>
        </div>

        <div className="space-y-4">
          <Card className="animate-surface-enter animate-surface-delay-2 p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Connection tools</p>
                <h3 className="mt-1 text-lg font-semibold text-ink">Connect or repair a source</h3>
                <p className="mt-2 text-sm text-[#596270]">Use these only when setup or reconnect work is needed.</p>
              </div>
            </div>

            <div className="mt-4 grid gap-3">
              <ConnectSourceCard
                provider="Canvas ICS"
                title="Student calendar feed"
                detail="Connect or update the calendar feed."
                connected={activeProviders.has("ics")}
                attention={activeSources.some((source) => source.provider === "ics" && sourceNeedsAttention(source))}
                href={withBasePath(basePath, "/sources/connect/canvas-ics")}
                icon={<CalendarSync className="h-5 w-5" />}
                iconShellClassName="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(31,94,255,0.1)] text-cobalt"
              />
              <ConnectSourceCard
                provider="Gmail"
                title="OAuth mailbox"
                detail="Connect Gmail if email changes should count."
                connected={activeProviders.has("gmail")}
                attention={activeSources.some((source) => source.provider === "gmail" && sourceNeedsAttention(source))}
                href={withBasePath(basePath, "/sources/connect/gmail")}
                icon={<Mailbox className="h-5 w-5" />}
                iconShellClassName="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(215,90,45,0.12)] text-ember"
              />
            </div>

            {!activeProviders.has("gmail") ? (
              <div className="mt-4">
                <Button variant="ghost" onClick={() => void startGmailConnect()}>
                  Connect Gmail now
                </Button>
              </div>
            ) : null}
          </Card>

          <Card className="animate-surface-enter animate-surface-delay-3 p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Archived</p>
                <h3 className="mt-1 text-lg font-semibold text-ink">Recover previous connections</h3>
              </div>
              <Badge tone="info">{archivedSources.length}</Badge>
            </div>

            <div className="mt-4 space-y-3">
              {archivedSources.length === 0 ? (
                <div className="rounded-[1.1rem] border border-dashed border-line/80 bg-white/40 p-5 text-sm text-[#596270]">No archived sources.</div>
              ) : (
                archivedSources.map((source) => (
                  <ArchivedSourceCard
                    key={source.source_id}
                    source={source}
                    onReactivate={reactivateSource}
                    busyReactivate={busyReactivate}
                    basePath={basePath}
                  />
                ))
              )}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
