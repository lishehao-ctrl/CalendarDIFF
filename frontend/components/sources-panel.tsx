"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArchiveRestore, CalendarSync, ChevronRight, Mailbox, RefreshCw, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/data-states";
import { SourceSyncProgress } from "@/components/source-sync-progress";
import { Sheet, SheetContent, SheetDescription, SheetDismissButton, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { WorkbenchLoadingShell } from "@/components/workbench-loading-shell";
import { startOnboardingGmailOAuth } from "@/lib/api/onboarding";
import { createOAuthSession, createSyncRequest, deleteSource as deleteSourceRequest, getSyncRequest, listSources, sourceListCacheKey, updateSource } from "@/lib/api/sources";
import { withBasePath } from "@/lib/demo-mode";
import { translate } from "@/lib/i18n/runtime";
import { invalidateSourceCaches } from "@/lib/source-cache";
import { usePageMetadata } from "@/lib/use-page-metadata";
import { useResponsiveTier } from "@/lib/use-responsive-tier";
import { useApiResource } from "@/lib/use-api-resource";
import { useSourceObservabilityMap } from "@/lib/use-source-observability-map";
import { workbenchPanelClassName, workbenchStateSurfaceClassName, workbenchSupportPanelClassName } from "@/lib/workbench-styles";
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
      title: source.provider === "gmail" ? translate("sources.reconnectGmail") : translate("sources.toolsSection"),
      detail: translate("sources.insightNeedsTrust"),
    };
  }

  if (source.sync_progress) {
    return {
      title: source.sync_progress.label || translate("common.status.running"),
      detail: null,
    };
  }

  return {
    title: translate("common.status.ok"),
    detail: null,
  };
}

function formatSourceTitle(source: SourceRow) {
  if (source.provider === "ics") return "Canvas ICS";
  return source.display_name || source.source_key;
}

function formatSourceSubtitle(source: SourceRow) {
  if (source.provider === "ics") {
    return translate("sources.detail.studentCalendarFeed");
  }
  return source.oauth_account_email || `${formatStatusLabel(source.source_kind, "Email")} · ${source.source_key}`;
}

function productPhaseLabel(phase: SourceRow["source_product_phase"] | SourceObservabilityResponse["source_product_phase"]) {
  switch (phase) {
    case "importing_baseline":
      return formatStatusLabel("baseline_import");
    case "needs_initial_review":
      return formatStatusLabel("initial_review");
    case "monitoring_live":
      return formatStatusLabel("monitoring_live");
    case "needs_attention":
      return formatStatusLabel("attention_required");
    default:
      return translate("sources.detail.phaseUnavailable");
  }
}

function trustStateLabel(trustState: SourceRecovery["trust_state"] | null | undefined) {
  switch (trustState) {
    case "trusted":
      return formatStatusLabel("trusted");
    case "stale":
      return formatStatusLabel("stale");
    case "partial":
      return formatStatusLabel("partial");
    case "blocked":
      return formatStatusLabel("blocked");
    default:
      return translate("sources.detail.trustUnavailable");
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
    <div className={workbenchSupportPanelClassName("default", "p-3.5")}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className={iconShellClassName}>{icon}</div>
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{provider}</p>
            <h3 className="mt-1 text-sm font-semibold text-ink">{title}</h3>
            <p className="mt-1 text-xs text-[#596270]">{detail}</p>
          </div>
        </div>
        <Badge tone={attention ? "pending" : connected ? "approved" : "info"}>
          {attention ? formatStatusLabel("attention") : connected ? translate("sources.connectCard.connected") : translate("sources.connectCard.notConnected")}
        </Badge>
      </div>
      <div className="mt-3">
        <Button asChild size="sm" variant={connected ? "ghost" : "secondary"}>
          <Link href={href}>
            {connected ? translate("sources.connectCard.manage") : translate("common.actions.connect")}
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
  wideActions,
}: {
  source: SourceRow;
  observability: SourceObservabilityResponse | undefined;
  syncLabel?: string;
  onSync: (sourceId: number) => void;
  onDelete: (sourceId: number, provider: string) => void;
  busyDelete: number | null;
  basePath: string;
  wideActions: boolean;
}) {
  const recovery = resolveRecovery(source, observability);
  const productPhase = resolveProductPhase(source, observability);
  const needsAttention = recovery ? recovery.trust_state !== "trusted" : sourceNeedsAttention(source);
  const normalizedSyncLabel = syncLabel?.toLowerCase() || "";
  const showSyncBadge = normalizedSyncLabel !== "" && normalizedSyncLabel !== "idle";
  const detailHref = withBasePath(basePath, `/sources/${source.source_id}`);
  const ctaClassName = wideActions ? "min-w-[10rem] justify-center" : "w-full justify-center";
  const primaryAction =
    recovery?.next_action === "reconnect_gmail" ? (
      <Button asChild className={ctaClassName}>
        <Link href={sourceSetupHref(basePath, source.provider)}>{translate("sources.reconnectGmail")}</Link>
      </Button>
    ) : recovery?.next_action === "update_ics" ? (
      <Button asChild className={ctaClassName}>
        <Link href={sourceSetupHref(basePath, source.provider)}>{translate("sources.updateCanvas")}</Link>
      </Button>
    ) : recovery?.next_action === "retry_sync" ? (
      <Button onClick={() => onSync(source.source_id)} className={ctaClassName}>
        <RefreshCw className="mr-2 h-4 w-4" />
        {recovery.next_action_label || translate("sources.retrySync")}
      </Button>
    ) : productPhase === "needs_initial_review" ? (
      <Button asChild className={ctaClassName}>
        <Link href={withBasePath(basePath, "/changes?bucket=initial_review")}>{translate("sources.openInitialReview")}</Link>
      </Button>
    ) : (
      <Button asChild className={ctaClassName}>
        <Link href={detailHref}>{translate("sources.openDetails")}</Link>
      </Button>
    );

  return (
    <Card
      className={workbenchPanelClassName(
        needsAttention ? "primary" : "secondary",
        "animate-surface-enter interactive-lift p-5",
      )}
    >
      <div className="min-w-0">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-base font-semibold text-ink">{formatSourceTitle(source)}</h3>
                <Badge tone="info">{productPhaseLabel(productPhase)}</Badge>
                <Badge tone={trustStateTone(recovery?.trust_state)}>{trustStateLabel(recovery?.trust_state)}</Badge>
              </div>
              <p className="mt-2 text-sm text-[#596270]">{formatSourceSubtitle(source)}</p>
            </div>
            <div className={cn("flex w-full shrink-0 flex-wrap gap-2", wideActions ? "md:ml-auto md:justify-end" : "")}>
              {primaryAction}
              <Button asChild variant="ghost" className={wideActions ? "min-w-[9rem] justify-center" : "w-full justify-center"}>
                <Link href={detailHref}>{translate("sources.openDetails")}</Link>
              </Button>
              <Button variant="ghost" className={wideActions ? "min-w-[9rem] justify-center" : "w-full justify-center"} onClick={() => onDelete(source.source_id, source.provider)} disabled={busyDelete === source.source_id}>
                <Trash2 className="mr-2 h-4 w-4" />
                {busyDelete === source.source_id ? translate("sources.archiving") : translate("sources.archive")}
              </Button>
            </div>
          </div>

          <div className={workbenchSupportPanelClassName("quiet", "p-4 text-sm text-[#314051]")}>
            <p className="font-medium text-ink">{recovery?.impact_summary || buildSourceInsight(source).title}</p>
            {!recovery?.impact_summary && buildSourceInsight(source).detail ? (
              <p className="mt-2 text-[#596270]">{buildSourceInsight(source).detail}</p>
            ) : null}
          </div>

          {showSyncBadge && source.sync_progress ? <SourceSyncProgress className="mt-1" progress={source.sync_progress} /> : null}
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
    <Card className={workbenchPanelClassName("secondary", "animate-surface-enter interactive-lift p-4")}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-medium text-ink">{formatSourceTitle(source)}</p>
          <p className="mt-1 text-sm text-[#596270]">{formatSourceSubtitle(source)}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => onReactivate(source.source_id)} disabled={busyReactivate === source.source_id}>
            <ArchiveRestore className="mr-2 h-4 w-4" />
            {busyReactivate === source.source_id ? translate("sources.reactivating") : translate("sources.reactivate")}
          </Button>
          <Button asChild variant="ghost">
            <Link href={withBasePath(basePath, `/sources/${source.source_id}`)}>{translate("sources.openDetails")}</Link>
          </Button>
        </div>
      </div>
    </Card>
  );
}

export function SourcesPanel({ basePath = "" }: { basePath?: string }) {
  usePageMetadata(translate("sources.heroTitle"), translate("sources.heroSummary"));
  const { isMobile, isTabletPortrait, isTabletWide, isDesktop } = useResponsiveTier();
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
  const [toolsOpen, setToolsOpen] = useState(false);
  const [observabilityRefreshNonce, setObservabilityRefreshNonce] = useState(0);
  const oauthQueryHandled = useRef(false);
  const toolsSheetSide = isDesktop || isTabletWide ? "right" : "bottom";
  const showWideSupportColumn = isDesktop || isTabletWide;
  const showBelowSupportCards = isTabletPortrait;

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
  const observabilityMap = useSourceObservabilityMap(activeSources, observabilityRefreshNonce);
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
  const refreshAll = useCallback(async (options?: { background?: boolean; force?: boolean; refreshObservability?: boolean }) => {
    await Promise.all([
      active.refresh({ background: options?.background, force: options?.force }),
      archived.refresh({ background: options?.background, force: options?.force }),
    ]);
    if (options?.refreshObservability) {
      setObservabilityRefreshNonce((current) => current + 1);
    }
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
          void refreshAll({ background: true, force: true, refreshObservability: true });
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
            setBanner({ tone: "info", text: options?.successMessage || translate("sources.syncSucceeded", { sourceId }) });
          } else {
            const failure =
              status.error_message ||
              status.connector_result?.error_message ||
              options?.failurePrefix ||
              translate("sources.syncFailedForSource", { sourceId });
            setBanner({ tone: "error", text: failure });
          }
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      await refreshAll({ background: true, force: true, refreshObservability: true });
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
      text: message || (status === "success" ? translate("sources.oauthSuccess") : translate("sources.oauthFailed")),
    });

    for (const key of oauthQueryKeys) {
      url.searchParams.delete(key);
    }
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);

    invalidateSourceCaches(sourceId ?? undefined);
    void refreshAll({ background: true, force: true, refreshObservability: true });
    if (status === "success" && requestId && sourceId) {
      void pollSyncRequest(sourceId, requestId, {
        successMessage: translate("sources.initialSyncSuccess"),
        failurePrefix: translate("sources.initialSyncFailed"),
      });
    }
  }, [pollSyncRequest, refreshAll]);

  async function triggerSync(sourceId: number) {
    setBanner(null);
    try {
      const created = await createSyncRequest(sourceId, { metadata: { kind: "ui_manual_sync" } });
      invalidateSourceCaches(sourceId);
      await pollSyncRequest(sourceId, created.request_id);
    } catch (err) {
      const text = err instanceof Error ? err.message : translate("sources.syncFailed");
      setSyncState((prev) => ({ ...prev, [sourceId]: "failed" }));
      setBanner({ tone: "error", text });
    }
  }

  async function archiveSource(sourceId: number, provider: string) {
    const confirmed = window.confirm(
      provider === "gmail"
        ? translate("sources.archiveConfirmGmail")
        : provider === "ics"
          ? translate("sources.archiveConfirmCanvas")
          : translate("sources.archiveConfirmGeneric"),
    );
    if (!confirmed) return;

    setBusyDelete(sourceId);
    setBanner(null);
    try {
      await deleteSourceRequest(sourceId);
      invalidateSourceCaches(sourceId);
      setBanner({
        tone: "info",
        text: provider === "gmail" ? translate("sources.archivedMailbox") : provider === "ics" ? translate("sources.archivedCanvas") : translate("sources.archivedSource"),
      });
      await refreshAll({ background: true, force: true, refreshObservability: true });
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("sources.archiveFailed") });
    } finally {
      setBusyDelete(null);
    }
  }

  async function reactivateSource(sourceId: number) {
    setBusyReactivate(sourceId);
    setBanner(null);
    try {
      await updateSource(sourceId, { is_active: true });
      invalidateSourceCaches(sourceId);
      setBanner({ tone: "info", text: translate("sources.reactivateSource", { sourceId }) });
      await refreshAll({ background: true, force: true, refreshObservability: true });
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("sources.reactivateFailed") });
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
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("sources.connectGmailFailed") });
    }
  }

  if ((active.loading && !active.data) || (archived.loading && !archived.data)) return <WorkbenchLoadingShell variant="sources" />;
  if (active.error) return <ErrorState message={active.error} />;
  if (archived.error) return <ErrorState message={archived.error} />;
  if (observabilityMap.error) return <ErrorState message={observabilityMap.error} />;

  const postureCard = (
    <Card className={workbenchPanelClassName("secondary", "p-4")}>
      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.needsAttention")}</p>
      <h3 className="mt-2 text-base font-semibold text-ink">{translate("sources.currentPostureTitle")}</h3>
      <div className="mt-4 space-y-3">
        {attentionSources.length > 0 ? (
          attentionSources.slice(0, 3).map((source) => (
            <div key={source.source_id} className={workbenchSupportPanelClassName("default", "p-3")}>
              <p className="font-medium text-ink">{formatSourceTitle(source)}</p>
              <p className="mt-1 text-sm text-[#596270]">{resolveRecovery(source, observabilityMap.data[source.source_id])?.impact_summary || source.last_error_message}</p>
            </div>
          ))
        ) : (
          <p className="text-sm text-[#596270]">{translate("sources.healthy")}</p>
        )}
      </div>
    </Card>
  );

  const toolsCard = (
    <Card className={workbenchPanelClassName("secondary", "p-4")}>
      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.toolsTitle")}</p>
      <h3 className="mt-2 text-base font-semibold text-ink">{translate("sources.connectRecoverTitle")}</h3>
      <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("sources.toolsSummary")}</p>
      <div className="mt-4 grid gap-3">
        <ConnectSourceCard
          provider="Canvas ICS"
          title={translate("sources.connectCanvas")}
          detail={translate("sources.connectCanvasDetail")}
          connected={activeProviders.has("ics")}
          attention={activeSources.some((source) => source.provider === "ics" && sourceNeedsAttention(source))}
          href={withBasePath(basePath, "/sources/connect/canvas-ics")}
          icon={<CalendarSync className="h-5 w-5" />}
          iconShellClassName="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(31,94,255,0.1)] text-cobalt"
        />
        <ConnectSourceCard
          provider="Gmail"
          title={translate("sources.connectGmail")}
          detail={translate("sources.connectGmailDetail")}
          connected={activeProviders.has("gmail")}
          attention={activeSources.some((source) => source.provider === "gmail" && sourceNeedsAttention(source))}
          href={withBasePath(basePath, "/sources/connect/gmail")}
          icon={<Mailbox className="h-5 w-5" />}
          iconShellClassName="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(215,90,45,0.12)] text-ember"
        />
      </div>
      {archivedSources.length > 0 ? (
        <div className="mt-4">
          <Button size="sm" variant="ghost" onClick={() => setToolsOpen(true)}>
            {translate("sources.archivedTitle")}
          </Button>
        </div>
      ) : null}
    </Card>
  );

  return (
    <div className="space-y-4">
      <div className="px-1">
        <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.heroEyebrow")}</p>
        <h2 className="mt-1 text-2xl font-semibold text-ink">{translate("sources.heroTitle")}</h2>
        <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("sources.heroSummary")}</p>
      </div>

      {banner ? (
        <Card className={workbenchStateSurfaceClassName(banner.tone === "error" ? "error" : "info", "p-4")}>
          <p className="text-sm text-[#314051]">{banner.text}</p>
        </Card>
      ) : null}

      {initialReviewReady.length > 0 ? (
        <Card className={workbenchStateSurfaceClassName("info", "animate-surface-enter p-4")}>
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.introEyebrow")}</p>
              <p className="mt-1 text-sm font-medium text-ink">
                {initialReviewReady.length === 1
                  ? translate("sources.initialReviewReadyOne")
                  : translate("sources.initialReviewReadyMany", { count: initialReviewReady.length })}
              </p>
            </div>
            <Button asChild size="sm">
              <Link href={withBasePath(basePath, "/changes?bucket=initial_review")}>{translate("sources.introOpen")}</Link>
            </Button>
          </div>
        </Card>
      ) : null}

      {initialReviewReady.length === 0 && baselineRunning.length > 0 ? (
        <Card className={workbenchStateSurfaceClassName("neutral", "animate-surface-enter p-4")}>
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.baselineEyebrow")}</p>
          <p className="mt-1 text-sm font-medium text-ink">
            {baselineRunning.length === 1
              ? translate("sources.baselineRunningOne")
              : translate("sources.baselineRunningMany", { count: baselineRunning.length })}
          </p>
        </Card>
      ) : null}

      <div className={cn("grid gap-5", showWideSupportColumn ? "lg:grid-cols-[minmax(0,1fr)_300px]" : "")}>
        <div className="space-y-4">
        <Card className={workbenchPanelClassName("secondary", "animate-surface-enter p-5")}>
          <div className="flex items-start justify-between gap-4">
            <div className="max-w-2xl">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.listEyebrow")}</p>
              <h3 className="mt-1 text-lg font-semibold text-ink">{translate("sources.listTitle")}</h3>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                {attentionSources.length > 0
                  ? translate("sources.attentionSummary", { count: attentionSources.length })
                  : translate("sources.noBlockingReview")}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge tone={attentionSources.length > 0 ? "pending" : "approved"}>
                {translate("sources.counts.attention", { count: attentionSources.length })}
              </Badge>
              <Badge tone="info">{translate("sources.counts.connected", { count: activeSources.length })}</Badge>
            </div>
          </div>

          <div className="mt-4 space-y-3">
            {activeSources.length === 0 ? (
              <EmptyState title={translate("sources.emptyTitle")} description={translate("sources.emptyDescription")} />
            ) : (
              <>
                {attentionSources.length > 0 ? (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-xs uppercase tracking-[0.18em] text-ember">{translate("sources.needsAttention")}</p>
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
                        wideActions={isTabletWide || isDesktop}
                      />
                    ))}
                  </div>
                ) : null}

                {healthySources.length > 0 ? (
                  <div className={`${attentionSources.length > 0 ? "border-t border-line/80 pt-4" : ""} space-y-3`}>
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.healthy")}</p>
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
                        wideActions={isTabletWide || isDesktop}
                      />
                    ))}
                  </div>
                ) : null}
              </>
            )}
          </div>

          {(archivedSources.length > 0 || activeProviders.size < 2) ? (
            <div className="mt-4 text-xs text-[#6d7885]">
              <button type="button" className="font-medium text-cobalt transition hover:text-[#1f4fd6]" onClick={() => setToolsOpen(true)}>
                {translate("sources.openSourceTools")}
              </button>
            </div>
          ) : null}
        </Card>
          {isMobile ? (
            <Card className={workbenchPanelClassName("secondary", "p-4")}>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.toolsTitle")}</p>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                {attentionSources.length > 0
                  ? translate("sources.attentionSummary", { count: attentionSources.length })
                  : translate("sources.noBlockingReview")}
              </p>
              <div className="mt-4">
                <Button size="sm" variant="ghost" onClick={() => setToolsOpen(true)}>
                  {translate("sources.openSourceTools")}
                </Button>
              </div>
            </Card>
          ) : null}

          {showBelowSupportCards ? (
            <div className="grid gap-4 md:grid-cols-2">
              {postureCard}
              {toolsCard}
            </div>
          ) : null}
        </div>

        {showWideSupportColumn ? <div className="space-y-4">{postureCard}{toolsCard}</div> : null}
      </div>

      <Sheet open={toolsOpen} onOpenChange={setToolsOpen}>
        <SheetContent side={toolsSheetSide} className="overflow-y-auto">
          <SheetHeader>
            <div>
              <SheetTitle>{translate("sources.toolsTitle")}</SheetTitle>
              <SheetDescription>{translate("sources.toolsSummary")}</SheetDescription>
            </div>
            <SheetDismissButton />
          </SheetHeader>

          <div className="mt-6 space-y-6">
            <div className="space-y-3">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.toolsSection")}</p>
              </div>
              <div className="grid gap-3">
                <ConnectSourceCard
                  provider="Canvas ICS"
                  title={translate("sources.connectCanvas")}
                  detail={translate("sources.connectCanvasDetail")}
                  connected={activeProviders.has("ics")}
                  attention={activeSources.some((source) => source.provider === "ics" && sourceNeedsAttention(source))}
                  href={withBasePath(basePath, "/sources/connect/canvas-ics")}
                  icon={<CalendarSync className="h-5 w-5" />}
                  iconShellClassName="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(31,94,255,0.1)] text-cobalt"
                />
                <ConnectSourceCard
                  provider="Gmail"
                  title={translate("sources.connectGmail")}
                  detail={translate("sources.connectGmailDetail")}
                  connected={activeProviders.has("gmail")}
                  attention={activeSources.some((source) => source.provider === "gmail" && sourceNeedsAttention(source))}
                  href={withBasePath(basePath, "/sources/connect/gmail")}
                  icon={<Mailbox className="h-5 w-5" />}
                  iconShellClassName="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(215,90,45,0.12)] text-ember"
                />
              </div>

              {!activeProviders.has("gmail") ? (
                <div className="pt-1">
                  <Button variant="ghost" onClick={() => void startGmailConnect()}>
                    {translate("sources.connectGmailNow")}
                  </Button>
                </div>
              ) : null}
            </div>

            <div className="space-y-3">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.archivedEyebrow")}</p>
                  <h3 className="mt-1 text-lg font-semibold text-ink">{translate("sources.archivedTitle")}</h3>
                </div>
                <Badge tone="info">{archivedSources.length}</Badge>
              </div>

              {archivedSources.length === 0 ? (
                <div className={workbenchSupportPanelClassName("quiet", "border-dashed p-5 text-sm text-[#596270]")}>{translate("sources.noArchived")}</div>
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
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
