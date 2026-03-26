"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { SourceRecoveryAgentCard } from "@/components/source-recovery-agent-card";
import { ArchiveRestore, ExternalLink, RefreshCw, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/data-states";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";
import { SourceSyncProgress } from "@/components/source-sync-progress";
import { WorkbenchLoadingShell } from "@/components/workbench-loading-shell";
import {
  createOAuthSession,
  createSyncRequest,
  deleteSource,
  getSourceObservability,
  getSourceLlmInvocations,
  getSourceSyncHistory,
  getSyncRequestLlmInvocations,
  listSources,
  sourceListCacheKey,
  sourceLlmInvocationsCacheKey,
  sourceObservabilityCacheKey,
  sourceSyncHistoryCacheKey,
  syncRequestLlmInvocationsCacheKey,
  updateSource,
} from "@/lib/api/sources";
import { withBasePath } from "@/lib/demo-mode";
import { intlDateLocale, translate } from "@/lib/i18n/runtime";
import { formatCount, formatDateTime, formatStatusLabel } from "@/lib/presenters";
import { invalidateSourceCaches } from "@/lib/source-cache";
import { formatElapsedMs } from "@/lib/source-observability";
import { usePageMetadata } from "@/lib/use-page-metadata";
import { useResponsiveTier } from "@/lib/use-responsive-tier";
import { workbenchPanelClassName, workbenchStateSurfaceClassName, workbenchSupportPanelClassName } from "@/lib/workbench-styles";
import type {
  LlmInvocationLogResponse,
  LlmInvocationSummaryResponse,
  SourceObservabilitySync,
  SourceOperatorGuidance,
  SourceRecovery,
  SourceRow,
  SourceSyncHistoryResponse,
  SourceLlmInvocationsResponse,
  SyncRequestLlmInvocationsResponse,
} from "@/lib/types";
import { useApiResource } from "@/lib/use-api-resource";
import { cn } from "@/lib/utils";

function sourceTitle(source: SourceRow) {
  if (source.provider === "ics") {
    return "Canvas ICS";
  }
  return source.display_name || source.oauth_account_email || source.source_key;
}

function sourceSubtitle(source: SourceRow) {
  if (source.provider === "ics") {
    return translate("sources.detail.studentCalendarFeed");
  }
  return source.oauth_account_email || translate("sources.detail.mailboxConnection");
}

function connectHref(basePath: string, provider: string) {
  return provider === "ics" ? withBasePath(basePath, "/sources/connect/canvas-ics") : withBasePath(basePath, "/sources/connect/gmail");
}

function productPhaseLabel(phase: SourceRow["source_product_phase"] | null | undefined) {
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

function guidanceTone(severity: SourceOperatorGuidance["severity"] | null | undefined) {
  switch (severity) {
    case "blocking":
      return "error";
    case "warning":
      return "pending";
    case "info":
    default:
      return "info";
  }
}

function formatUsd(value: number | null | undefined, pricingAvailable = true) {
  if (!pricingAvailable) {
    return translate("sources.detail.llmActivityPricingUnavailable");
  }
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return translate("common.labels.notAvailable");
  }
  const digits = value >= 1 ? 2 : value >= 0.01 ? 3 : 4;
  return new Intl.NumberFormat(intlDateLocale(), {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

function humanizeIdentifier(value: string | null | undefined) {
  if (!value) {
    return translate("common.labels.notAvailable");
  }
  if (value === "responses") {
    return "Responses API";
  }
  if (value === "chat_completions") {
    return "Chat Completions API";
  }
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function compactIdentifier(value: string) {
  return value.length > 14 ? `${value.slice(0, 12)}…` : value;
}

function countEntries(mapping: Record<string, number>) {
  return Object.entries(mapping)
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, 3);
}

function usageFact(label: string, value: string) {
  return (
    <div className={workbenchSupportPanelClassName("default", "p-3")}>
      <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{label}</p>
      <p className="mt-2 text-sm font-medium text-ink">{value}</p>
    </div>
  );
}

function CountBreakdown({
  label,
  entries,
  preserveLabel = false,
}: {
  label: string;
  entries: Array<[string, number]>;
  preserveLabel?: boolean;
}) {
  return (
    <div className={workbenchSupportPanelClassName("quiet", "p-4")}>
      <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{label}</p>
      {entries.length > 0 ? (
        <div className="mt-3 space-y-2">
          {entries.map(([entryLabel, count]) => (
            <div key={`${label}-${entryLabel}`} className="flex items-center justify-between gap-3 text-sm text-[#314051]">
              <span className="min-w-0 truncate">{preserveLabel ? entryLabel : humanizeIdentifier(entryLabel)}</span>
              <span className="font-medium text-ink">{formatCount(count)}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-3 text-sm text-[#596270]">{translate("common.labels.notAvailable")}</p>
      )}
    </div>
  );
}

function SyncRunCard({
  title,
  sync,
}: {
  title: string;
  sync: SourceObservabilitySync | null;
}) {
  return (
    <div className={workbenchSupportPanelClassName("default", "p-4")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{title}</p>
          <p className="mt-2 text-sm font-medium text-ink">{sync ? formatStatusLabel(sync.status) : translate("sources.detail.noRunYet")}</p>
        </div>
        {sync ? <Badge tone={sync.status === "FAILED" ? "error" : sync.status === "RUNNING" ? "pending" : "approved"}>{formatStatusLabel(sync.status)}</Badge> : null}
      </div>
      {sync ? (
        <>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {usageFact(translate("sources.observability.elapsed"), formatElapsedMs(sync.elapsed_ms || null))}
            {usageFact(translate("sources.observability.stage"), formatStatusLabel(sync.substage || sync.stage, translate("sources.detail.noStageSample")))}
            {usageFact(translate("sources.observability.updated"), formatDateTime(sync.updated_at))}
          </div>
          {sync.progress ? <SourceSyncProgress className="mt-4" progress={sync.progress} /> : null}
          {sync.error_message ? <p className="mt-4 text-sm leading-6 text-[#7f3d2a]">{sync.error_message}</p> : null}
        </>
      ) : (
        <p className="mt-4 text-sm text-[#596270]">{translate("sources.detail.noSampledRun")}</p>
      )}
    </div>
  );
}

export function SourceDetailPanel({ sourceId, basePath = "" }: { sourceId: number; basePath?: string }) {
  const { isTabletWide, isDesktop } = useResponsiveTier();
  const sources = useApiResource<SourceRow[]>(() => listSources({ status: "all" }), [], null, {
    cacheKey: sourceListCacheKey("all"),
  });
  const source = useMemo(() => (sources.data || []).find((row) => row.source_id === sourceId) || null, [sourceId, sources.data]);
  const canLoadSourceDetail = Boolean(source);
  const observability = useApiResource(
    () => (canLoadSourceDetail ? getSourceObservability(sourceId) : Promise.resolve(null)),
    [sourceId, canLoadSourceDetail],
    null,
    {
    cacheKey: sourceObservabilityCacheKey(sourceId),
    },
  );
  const history = useApiResource<SourceSyncHistoryResponse | null>(
    () => (canLoadSourceDetail ? getSourceSyncHistory(sourceId, { limit: 8 }) : Promise.resolve(null)),
    [sourceId, canLoadSourceDetail],
    null,
    {
    cacheKey: sourceSyncHistoryCacheKey(sourceId, 8),
    },
  );
  const sourceLlmActivity = useApiResource<SourceLlmInvocationsResponse | null>(
    () => (canLoadSourceDetail ? getSourceLlmInvocations(sourceId, { limit: 8 }) : Promise.resolve(null)),
    [sourceId, canLoadSourceDetail],
    null,
    {
      cacheKey: sourceLlmInvocationsCacheKey(sourceId, { limit: 8 }),
    },
  );
  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [busySync, setBusySync] = useState(false);
  const [busyArchive, setBusyArchive] = useState(false);
  const [busyReactivate, setBusyReactivate] = useState(false);
  const [busyReconnect, setBusyReconnect] = useState(false);
  const activeSync = observability.data?.active || null;
  const activeRequestId = observability.data?.active_request_id || activeSync?.request_id || null;
  const requestLlmActivity = useApiResource<SyncRequestLlmInvocationsResponse | null>(
    () => (canLoadSourceDetail && activeRequestId ? getSyncRequestLlmInvocations(activeRequestId, { limit: 8 }) : Promise.resolve(null)),
    [sourceId, canLoadSourceDetail, activeRequestId],
    null,
    {
      cacheKey: activeRequestId ? syncRequestLlmInvocationsCacheKey(activeRequestId, 8) : undefined,
    },
  );
  const previewSourceRecovery = observability.data?.source_recovery || source?.source_recovery || null;

  usePageMetadata(
    source ? sourceTitle(source) : translate("sources.detail.pageEyebrow"),
    source ? previewSourceRecovery?.impact_summary || sourceSubtitle(source) : translate("sources.heroSummary"),
  );

  const shouldPollActiveSync = Boolean(
    (activeSync && activeSync.status !== "SUCCEEDED" && activeSync.status !== "FAILED") ||
      source?.runtime_state === "running" ||
      source?.runtime_state === "queued" ||
      source?.runtime_state === "rebind_pending" ||
      source?.sync_state === "running" ||
      source?.sync_state === "queued",
  );

  const refreshAll = useCallback(async (options?: { background?: boolean; force?: boolean }) => {
    await sources.refresh({ background: options?.background, force: options?.force });
    if (!canLoadSourceDetail) {
      return;
    }
    await Promise.all([
      observability.refresh({ background: options?.background, force: options?.force }),
      history.refresh({ background: options?.background, force: options?.force }),
      sourceLlmActivity.refresh({ background: options?.background, force: options?.force }),
      requestLlmActivity.refresh({ background: options?.background, force: options?.force }),
    ]);
  }, [canLoadSourceDetail, history, observability, requestLlmActivity, sourceLlmActivity, sources]);

  useEffect(() => {
    if (!shouldPollActiveSync) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void refreshAll({ background: true, force: true });
    }, 2000);
    return () => window.clearInterval(intervalId);
  }, [refreshAll, shouldPollActiveSync]);

  async function runSync() {
    setBusySync(true);
    setBanner(null);
    try {
      await createSyncRequest(sourceId, { metadata: { kind: "ui_source_detail_sync" } });
      invalidateSourceCaches(sourceId);
      setBanner({ tone: "info", text: translate("sources.detail.syncQueued") });
      await refreshAll({ force: true });
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("sources.detail.runSyncFailed") });
    } finally {
      setBusySync(false);
    }
  }

  async function archiveSource() {
    setBusyArchive(true);
    setBanner(null);
    try {
      await deleteSource(sourceId);
      invalidateSourceCaches(sourceId);
      setBanner({ tone: "info", text: translate("sources.detail.archiveSuccess") });
      await refreshAll({ force: true });
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("sources.detail.archiveFailed") });
    } finally {
      setBusyArchive(false);
    }
  }

  async function reactivateSource() {
    setBusyReactivate(true);
    setBanner(null);
    try {
      await updateSource(sourceId, { is_active: true });
      invalidateSourceCaches(sourceId);
      setBanner({ tone: "info", text: translate("sources.detail.reactivateSuccess") });
      await refreshAll({ force: true });
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("sources.detail.reactivateFailed") });
    } finally {
      setBusyReactivate(false);
    }
  }

  async function reconnectSource() {
    if (!source) return;
    setBusyReconnect(true);
    setBanner(null);
    try {
      const session = await createOAuthSession(source.source_id, { provider: source.provider });
      window.location.assign(session.authorization_url);
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("sources.detail.reconnectFailed") });
      setBusyReconnect(false);
    }
  }

  if (sources.loading && !sources.data) {
    return <WorkbenchLoadingShell variant="source-detail" />;
  }
  if (sources.error && !sources.data) return <ErrorState message={`${translate("sources.detail.sourceLoadFailed")} ${sources.error}`} />;
  if (!source) {
    return <EmptyState title={translate("sources.detail.sourceNotFoundTitle")} description={translate("sources.detail.sourceNotFoundDescription")} />;
  }

  const bootstrap = observability.data?.bootstrap || null;
  const bootstrapSummary = observability.data?.bootstrap_summary || null;
  const latestReplay = observability.data?.latest_replay || null;
  const sourceRecovery = observability.data?.source_recovery || source.source_recovery || null;
  const sourceProductPhase = observability.data?.source_product_phase || source.source_product_phase || null;
  const operatorGuidance = observability.data?.operator_guidance || source.operator_guidance || null;
  const showingOperatorGuidance = Boolean(operatorGuidance?.message && operatorGuidance.message !== sourceRecovery?.impact_summary);
  const requestActivityHasItems = Boolean((requestLlmActivity.data?.items || []).length > 0);
  const sourceActivityHasItems = Boolean((sourceLlmActivity.data?.items || []).length > 0);
  const usingRequestActivity = Boolean(activeRequestId && requestActivityHasItems);
  const llmActivityData = usingRequestActivity
    ? requestLlmActivity.data
    : sourceActivityHasItems
      ? sourceLlmActivity.data
      : requestLlmActivity.data || sourceLlmActivity.data;
  const llmActivityLoading =
    (activeRequestId ? requestLlmActivity.loading : false) ||
    (!requestActivityHasItems && sourceLlmActivity.loading && !sourceLlmActivity.data);
  const llmActivityError =
    requestLlmActivity.error && !requestActivityHasItems && !sourceActivityHasItems
      ? requestLlmActivity.error
      : !sourceActivityHasItems
        ? sourceLlmActivity.error
        : null;
  const llmActivityItems = llmActivityData?.items || [];
  const llmActivitySummary = llmActivityData?.summary as LlmInvocationSummaryResponse | undefined;
  const needsReconnect =
    sourceRecovery?.next_action === "reconnect_gmail" ||
    Boolean(source.last_error_message) ||
    source.oauth_connection_status === "not_connected";
  const bootstrapConnector = bootstrap?.connector_result && typeof bootstrap.connector_result === "object" ? (bootstrap.connector_result as Record<string, unknown>) : null;
  const bootstrapRecordsCount = typeof bootstrapConnector?.records_count === "number" ? bootstrapConnector.records_count : null;
  const showSupportColumn = isTabletWide || isDesktop;

  return (
    <div className="space-y-5">
      <Card className={workbenchPanelClassName("secondary", "animate-surface-enter p-5 md:p-6")}>
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-3xl">
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.detail.pageEyebrow")}</p>
            <h2 className="mt-2 text-2xl font-semibold text-ink">{sourceTitle(source)}</h2>
            <p className="mt-2 text-sm leading-6 text-[#596270]">{sourceRecovery?.impact_summary || sourceSubtitle(source)}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge tone="info">{formatStatusLabel(source.provider)}</Badge>
              <Badge tone={source.is_active ? "approved" : "info"}>{source.is_active ? translate("sources.detail.active") : translate("sources.detail.archived")}</Badge>
              <Badge tone="info">{productPhaseLabel(sourceProductPhase)}</Badge>
              <Badge tone={trustStateTone(sourceRecovery?.trust_state)}>{trustStateLabel(sourceRecovery?.trust_state)}</Badge>
            </div>
            {sourceRecovery?.next_action_label ? (
              <p className="mt-3 text-sm text-[#314051]">{translate("sources.detail.nextStep", { label: sourceRecovery.next_action_label })}</p>
            ) : null}
          </div>
          <div className={cn("grid w-full gap-2 sm:grid-cols-2", showSupportColumn ? "lg:flex lg:w-auto lg:max-w-[420px] lg:flex-wrap lg:justify-end" : "")}>
            {sourceProductPhase === "needs_initial_review" ? (
              <Button asChild size="sm" className="w-full xl:w-auto">
                <Link href={withBasePath(basePath, "/changes?bucket=initial_review")}>{translate("sources.detail.openInitialReview")}</Link>
              </Button>
            ) : sourceRecovery?.next_action === "reconnect_gmail" && source.provider === "gmail" ? (
              <Button size="sm" className="w-full xl:w-auto" onClick={() => void reconnectSource()} disabled={busyReconnect}>
                <ExternalLink className="mr-2 h-4 w-4" />
                {busyReconnect ? translate("sources.detail.redirecting") : sourceRecovery.next_action_label}
              </Button>
            ) : sourceRecovery?.next_action === "update_ics" && source.provider === "ics" ? (
              <Button asChild size="sm" className="w-full xl:w-auto">
                <Link href={connectHref(basePath, source.provider)}>{sourceRecovery.next_action_label}</Link>
              </Button>
            ) : (
              <Button size="sm" className="w-full xl:w-auto" onClick={() => void runSync()} disabled={busySync || !source.is_active}>
                <RefreshCw className="mr-2 h-4 w-4" />
                {busySync ? translate("sources.detail.running") : sourceRecovery?.next_action === "retry_sync" ? sourceRecovery.next_action_label : translate("sources.detail.runSync")}
              </Button>
            )}
            {source.provider === "gmail" ? (
              sourceRecovery?.next_action === "reconnect_gmail" ? (
                <Button asChild size="sm" variant="soft" className="w-full xl:w-auto">
                  <Link href={withBasePath(basePath, `/sources/${sourceId}`)}>{translate("sources.openDetails")}</Link>
                </Button>
              ) : (
                <Button size="sm" variant="soft" className="w-full xl:w-auto" onClick={() => void reconnectSource()} disabled={busyReconnect}>
                  <ExternalLink className="mr-2 h-4 w-4" />
                  {busyReconnect ? translate("sources.detail.redirecting") : needsReconnect ? sourceRecovery?.next_action_label || translate("sources.reconnectGmail") : translate("sources.detail.openGmailConnection")}
                </Button>
              )
            ) : (
              sourceRecovery?.next_action === "update_ics" ? (
                <Button asChild size="sm" variant="soft" className="w-full xl:w-auto">
                  <Link href={withBasePath(basePath, `/sources/${sourceId}`)}>{translate("sources.openDetails")}</Link>
                </Button>
              ) : (
                <Button asChild size="sm" variant="soft" className="w-full xl:w-auto">
                  <Link href={connectHref(basePath, source.provider)}>{translate("sources.detail.openConnectionFlow")}</Link>
                </Button>
              )
            )}
            {source.is_active ? (
              <Button size="sm" variant="ghost" className="w-full xl:w-auto" onClick={() => void archiveSource()} disabled={busyArchive}>
                <Trash2 className="mr-2 h-4 w-4" />
                {busyArchive ? translate("sources.archiving") : translate("sources.archive")}
              </Button>
            ) : (
              <Button size="sm" variant="ghost" className="w-full xl:w-auto" onClick={() => void reactivateSource()} disabled={busyReactivate}>
                <ArchiveRestore className="mr-2 h-4 w-4" />
                {busyReactivate ? translate("sources.reactivating") : translate("sources.reactivate")}
              </Button>
            )}
          </div>
        </div>
      </Card>

      {banner ? (
        <Card className={workbenchStateSurfaceClassName(banner.tone === "error" ? "error" : "info", "p-4")}>
          <p className="text-sm text-[#314051]">{banner.text}</p>
        </Card>
      ) : null}

      <div className={cn("grid gap-5", showSupportColumn ? "lg:grid-cols-[minmax(0,1.08fr)_340px]" : "")}>
        <div className="space-y-4">
          <Card className={workbenchPanelClassName("secondary", "animate-surface-enter p-5")} data-testid="source-detail-current-health">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.detail.currentPosture")}</p>
          {observability.loading && !observability.data ? (
            <PanelLoadingPlaceholder rows={2} className="mt-4 p-4" />
          ) : observability.error && !observability.data ? (
            <div className={workbenchStateSurfaceClassName("error", "mt-4 p-4 text-sm text-[#7f3d2a]")}>
              {`${translate("sources.detail.postureLoadFailed")} ${observability.error}`}
            </div>
          ) : (
            <div className={workbenchSupportPanelClassName("default", "mt-4 p-4")}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-ink">{sourceRecovery?.impact_summary || translate("sources.detail.recoveryUnavailable")}</p>
                  <p className="mt-2 text-sm text-[#596270]">{productPhaseLabel(sourceProductPhase)} · {trustStateLabel(sourceRecovery?.trust_state)}</p>
                </div>
                <Badge tone={trustStateTone(sourceRecovery?.trust_state)}>{trustStateLabel(sourceRecovery?.trust_state)}</Badge>
              </div>
              {sourceRecovery ? (
                <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {usageFact(translate("sources.detail.nextAction"), sourceRecovery.next_action_label)}
                  {usageFact(translate("sources.detail.lastGoodSync"), formatDateTime(sourceRecovery.last_good_sync_at, translate("sources.detail.notRecorded")))}
                  {usageFact(translate("sources.detail.degradedSince"), formatDateTime(sourceRecovery.degraded_since, translate("sources.detail.notDegraded")))}
                </div>
              ) : null}
              {sourceRecovery?.recovery_steps?.length ? (
                <div className={workbenchSupportPanelClassName("quiet", "mt-4 p-4")}>
                  <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("sources.detail.recoverySteps")}</p>
                  <div className="mt-3 space-y-2 text-sm text-[#314051]">
                    {sourceRecovery.recovery_steps.map((step) => (
                      <p key={step}>{step}</p>
                    ))}
                  </div>
                </div>
              ) : null}
              {showingOperatorGuidance ? (
                <div className={workbenchSupportPanelClassName("quiet", "mt-4 p-4")}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("sources.detail.operatorGuidance")}</p>
                      <p className="mt-2 text-sm font-medium text-ink">{operatorGuidance?.message}</p>
                    </div>
                    <Badge tone={guidanceTone(operatorGuidance?.severity)}>{formatStatusLabel(operatorGuidance?.severity, translate("common.labels.unknown"))}</Badge>
                  </div>
                  {operatorGuidance?.related_request_id ? (
                    <p className="mt-3 text-sm text-[#596270]">
                      {translate("sources.detail.relatedRequest")}: <span className="font-mono text-[12px] text-[#314051]">{operatorGuidance.related_request_id}</span>
                    </p>
                  ) : null}
                </div>
              ) : null}
              {activeSync ? (
                <>
                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    {usageFact(translate("sources.detail.currentRun"), formatStatusLabel(activeSync.status))}
                    {usageFact(translate("sources.observability.updated"), formatDateTime(activeSync.updated_at))}
                  </div>
                  {activeSync.progress ? <SourceSyncProgress className="mt-4" progress={activeSync.progress} /> : null}
                </>
              ) : source.sync_progress ? (
                <SourceSyncProgress className="mt-4" progress={source.sync_progress} />
              ) : null}
            </div>
          )}
          </Card>

          <Card className={workbenchPanelClassName("secondary", "animate-surface-enter p-5")}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="max-w-3xl">
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.detail.llmActivity")}</p>
                <h3 className="mt-2 text-base font-semibold text-ink">{translate("sources.detail.llmActivityTitle")}</h3>
                <p className="mt-2 text-sm leading-6 text-[#596270]">
                  {usingRequestActivity ? translate("sources.detail.llmActivityCurrentRequest") : translate("sources.detail.llmActivityRecentSource")}
                </p>
              </div>
            </div>
            {llmActivityLoading ? (
              <PanelLoadingPlaceholder rows={2} className="mt-4 p-4" />
            ) : llmActivityError && !llmActivityData ? (
              <div className={workbenchStateSurfaceClassName("error", "mt-4 p-4 text-sm text-[#7f3d2a]")}>
                {`${translate("sources.detail.llmActivityLoadFailed")} ${llmActivityError}`}
              </div>
            ) : llmActivityItems.length === 0 ? (
              <div className={workbenchSupportPanelClassName("default", "mt-4 p-4")}>
                <p className="text-sm font-medium text-ink">{translate("sources.detail.llmActivityEmptyTitle")}</p>
                <p className="mt-2 text-sm leading-6 text-[#596270]">
                  {usingRequestActivity ? translate("sources.detail.llmActivityCurrentRequestEmpty") : translate("sources.detail.llmActivityEmptyDescription")}
                </p>
              </div>
            ) : (
              <>
                <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {usageFact(
                    translate("sources.detail.llmActivityScope"),
                    usingRequestActivity && activeRequestId ? compactIdentifier(activeRequestId) : translate("common.labels.recent"),
                  )}
                  {usageFact(translate("sources.detail.llmActivityTotalCalls"), formatCount(llmActivitySummary?.total_count || 0))}
                  {usageFact(translate("sources.detail.llmActivitySucceeded"), formatCount(llmActivitySummary?.success_count || 0))}
                  {usageFact(translate("sources.detail.llmActivityFailed"), formatCount(llmActivitySummary?.failure_count || 0))}
                  {usageFact(translate("sources.detail.llmActivityAvgLatency"), formatElapsedMs(llmActivitySummary?.avg_latency_ms || null))}
                  {usageFact(translate("sources.detail.llmActivityTotalTokens"), formatCount(llmActivitySummary?.total_tokens || 0))}
                  {usageFact(
                    translate("sources.detail.llmActivityEstimatedCost"),
                    formatUsd(llmActivitySummary?.estimated_cost_usd, llmActivitySummary?.pricing_available !== false),
                  )}
                </div>

                <div className="mt-4 grid gap-3 xl:grid-cols-3">
                  <CountBreakdown
                    label={translate("sources.detail.llmActivityModels")}
                    entries={countEntries(llmActivitySummary?.model_counts || {})}
                    preserveLabel
                  />
                  <CountBreakdown label={translate("sources.detail.llmActivityProtocols")} entries={countEntries(llmActivitySummary?.protocol_counts || {})} />
                  <CountBreakdown label={translate("sources.detail.llmActivityTasks")} entries={countEntries(llmActivitySummary?.task_counts || {})} />
                </div>

                <div className="mt-4 space-y-3">
                  <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("sources.detail.llmActivityRecentCalls")}</p>
                  {llmActivityItems.slice(0, 4).map((item: LlmInvocationLogResponse, index: number) => (
                    <div
                      key={`${item.request_id || "requestless"}-${item.created_at}-${index}`}
                      className={workbenchSupportPanelClassName("quiet", "p-4")}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="text-sm font-medium text-ink">{humanizeIdentifier(item.task_name)}</p>
                            <Badge tone={item.success ? "approved" : "error"}>{formatStatusLabel(item.success ? "succeeded" : "failed")}</Badge>
                          </div>
                          <div className="mt-3 grid gap-2 text-sm text-[#596270]">
                            <p>{formatDateTime(item.created_at)} · {item.model}</p>
                            <p>{humanizeIdentifier(item.protocol)} · {formatElapsedMs(item.latency_ms)} · {formatUsd(item.estimated_cost_usd)}</p>
                          </div>
                          {item.error_code ? <p className="mt-3 text-sm text-[#7f3d2a]">{item.error_code}</p> : null}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </Card>

          <Card className={workbenchPanelClassName("secondary", "animate-surface-enter p-5")}>
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.detail.bootstrap")}</p>
          {observability.loading && !observability.data ? (
            <PanelLoadingPlaceholder rows={2} className="mt-4 p-4" />
          ) : observability.error && !observability.data ? (
            <div className={workbenchStateSurfaceClassName("error", "mt-4 p-4 text-sm text-[#7f3d2a]")}>
              {`${translate("sources.detail.postureLoadFailed")} ${observability.error}`}
            </div>
          ) : (
              <>
                <div className="mt-4">
                  <SyncRunCard title={translate("sources.detail.bootstrapRun")} sync={bootstrap} />
                </div>
                <div className={workbenchSupportPanelClassName("quiet", "mt-4 p-4")}>
                  <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("sources.detail.importSummary")}</p>
                  <div className="mt-4 grid gap-3 md:grid-cols-3">
                    {usageFact(translate("sources.detail.imported"), String(bootstrapSummary?.imported_count || 0))}
                    {usageFact(translate("sources.detail.needsReview"), String(bootstrapSummary?.review_required_count || 0))}
                    {usageFact(translate("sources.detail.ignored"), String(bootstrapSummary?.ignored_count || 0))}
                    {usageFact(translate("sources.detail.conflicts"), String(bootstrapSummary?.conflict_count || 0))}
                    {usageFact(translate("sources.detail.recordsScanned"), bootstrapRecordsCount !== null ? String(bootstrapRecordsCount) : "—")}
                    {usageFact(translate("sources.detail.bootstrapState"), formatStatusLabel(bootstrapSummary?.state, translate("common.labels.unknown")))}
                  </div>
                  {bootstrapSummary?.review_required_count ? (
                    <p className="mt-4 text-xs leading-5 text-[#6d7885]">
                      {translate("sources.detail.baselineReviewWaiting")}
                    </p>
                  ) : null}
                </div>
              </>
            )}
          </Card>

          <Card className={workbenchPanelClassName("secondary", "animate-surface-enter p-5")}>
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.detail.replayHistory")}</p>
          {history.loading && !history.data ? (
            <PanelLoadingPlaceholder rows={2} className="mt-4 p-4" />
          ) : history.error && !history.data ? (
            <div className={workbenchStateSurfaceClassName("error", "mt-4 p-4 text-sm text-[#7f3d2a]")}>
              {`${translate("sources.detail.historyLoadFailed")} ${history.error}`}
            </div>
          ) : (
              <div className="mt-4 space-y-3">
                <SyncRunCard title={translate("sources.detail.latestReplay")} sync={latestReplay} />
                {(history.data?.items || []).slice(0, 6).map((item) => (
                  <div key={item.request_id} className={workbenchSupportPanelClassName("default", "p-4")}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium text-ink">{translate("sources.detail.replayRunLabel", { status: formatStatusLabel(item.status) })}</p>
                        <p className="mt-1 text-sm text-[#596270]">{formatDateTime(item.updated_at)}</p>
                      </div>
                      <Badge tone={item.status === "FAILED" ? "error" : item.status === "RUNNING" ? "pending" : "approved"}>
                        {formatElapsedMs(item.elapsed_ms || null)}
                      </Badge>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        <div className="space-y-4">
          <Card className={workbenchPanelClassName("secondary", "animate-surface-enter p-5")}>
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.detail.connection")}</p>
            <div className="mt-4 grid gap-3">
              {usageFact(translate("sources.detail.provider"), formatStatusLabel(source.provider))}
              {usageFact(translate("sources.detail.displayName"), source.display_name || sourceTitle(source))}
              {usageFact(translate("sources.detail.account"), source.oauth_account_email || translate("sources.detail.notApplicable"))}
              {usageFact(translate("sources.detail.lifecycle"), formatStatusLabel(source.lifecycle_state || (source.is_active ? "active" : "archived")))}
              {usageFact(translate("sources.detail.lastPolled"), formatDateTime(source.last_polled_at, translate("sources.detail.never")))}
              {usageFact(translate("sources.detail.nextPoll"), formatDateTime(source.next_poll_at, translate("sources.detail.notScheduled")))}
            </div>
          </Card>

          <SourceRecoveryAgentCard sourceId={sourceId} basePath={basePath} />
        </div>
      </div>
    </div>
  );
}
