"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArchiveRestore, ExternalLink, RefreshCw, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/data-states";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";
import { SourceSyncProgress } from "@/components/source-sync-progress";
import {
  createOAuthSession,
  createSyncRequest,
  deleteSource,
  getSourceObservability,
  getSourceSyncHistory,
  listSources,
  sourceListCacheKey,
  sourceObservabilityCacheKey,
  sourceSyncHistoryCacheKey,
  updateSource,
} from "@/lib/api/sources";
import { withBasePath } from "@/lib/demo-mode";
import { translate } from "@/lib/i18n/runtime";
import { formatCount, formatDateTime, formatStatusLabel } from "@/lib/presenters";
import { invalidateSourceCaches } from "@/lib/source-cache";
import { formatElapsedMs } from "@/lib/source-observability";
import type { SourceObservabilitySync, SourceRecovery, SourceRow, SourceSyncHistoryResponse } from "@/lib/types";
import { useApiResource } from "@/lib/use-api-resource";

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

function usageFact(label: string, value: string) {
  return (
    <div className="rounded-[1rem] border border-line/80 bg-white/75 p-3">
      <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{label}</p>
      <p className="mt-2 text-sm font-medium text-ink">{value}</p>
    </div>
  );
}

function usageSummary(sync: SourceObservabilitySync | null) {
  if (!sync?.llm_usage || typeof sync.llm_usage !== "object") {
    return null;
  }
  const usage = sync.llm_usage as Record<string, unknown>;
  const totalTokens = typeof usage.total_tokens === "number" ? formatCount(usage.total_tokens) : translate("common.labels.notAvailable");
  const cachedTokens = typeof usage.cached_input_tokens === "number" ? formatCount(usage.cached_input_tokens) : "0";
  const latencyMs = typeof usage.latency_ms_total === "number" ? `${Math.round(usage.latency_ms_total)} ms` : translate("common.labels.notAvailable");
  return { totalTokens, cachedTokens, latencyMs };
}

function SyncRunCard({
  title,
  sync,
}: {
  title: string;
  sync: SourceObservabilitySync | null;
}) {
  const usage = usageSummary(sync);
  return (
    <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
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
          {usage ? (
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              {usageFact(translate("sources.observability.tokens"), usage.totalTokens)}
              {usageFact(translate("sources.observability.cachedInput"), usage.cachedTokens)}
              {usageFact(translate("sources.observability.latency"), usage.latencyMs)}
            </div>
          ) : null}
          {sync.error_message ? <p className="mt-4 text-sm leading-6 text-[#7f3d2a]">{sync.error_message}</p> : null}
        </>
      ) : (
        <p className="mt-4 text-sm text-[#596270]">{translate("sources.detail.noSampledRun")}</p>
      )}
    </div>
  );
}

export function SourceDetailPanel({ sourceId, basePath = "" }: { sourceId: number; basePath?: string }) {
  const sources = useApiResource<SourceRow[]>(() => listSources({ status: "all" }), [], null, {
    cacheKey: sourceListCacheKey("all"),
  });
  const observability = useApiResource(() => getSourceObservability(sourceId), [sourceId], null, {
    cacheKey: sourceObservabilityCacheKey(sourceId),
  });
  const history = useApiResource<SourceSyncHistoryResponse>(() => getSourceSyncHistory(sourceId, { limit: 8 }), [sourceId], null, {
    cacheKey: sourceSyncHistoryCacheKey(sourceId, 8),
  });
  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [busySync, setBusySync] = useState(false);
  const [busyArchive, setBusyArchive] = useState(false);
  const [busyReactivate, setBusyReactivate] = useState(false);
  const [busyReconnect, setBusyReconnect] = useState(false);

  const source = useMemo(() => (sources.data || []).find((row) => row.source_id === sourceId) || null, [sourceId, sources.data]);
  const activeSync = observability.data?.active || null;

  const shouldPollActiveSync = Boolean(
    (activeSync && activeSync.status !== "SUCCEEDED" && activeSync.status !== "FAILED") ||
      source?.runtime_state === "running" ||
      source?.runtime_state === "queued" ||
      source?.runtime_state === "rebind_pending" ||
      source?.sync_state === "running" ||
      source?.sync_state === "queued",
  );

  const refreshAll = useCallback(async (options?: { background?: boolean; force?: boolean }) => {
    await Promise.all([
      sources.refresh({ background: options?.background, force: options?.force }),
      observability.refresh({ background: options?.background, force: options?.force }),
      history.refresh({ background: options?.background, force: options?.force }),
    ]);
  }, [history, observability, sources]);

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
    return <PanelLoadingPlaceholder rows={3} />;
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
  const needsReconnect =
    sourceRecovery?.next_action === "reconnect_gmail" ||
    Boolean(source.last_error_message) ||
    source.oauth_connection_status === "not_connected";
  const bootstrapConnector = bootstrap?.connector_result && typeof bootstrap.connector_result === "object" ? (bootstrap.connector_result as Record<string, unknown>) : null;
  const bootstrapRecordsCount = typeof bootstrapConnector?.records_count === "number" ? bootstrapConnector.records_count : null;

  return (
    <div className="space-y-5">
      <Card className="animate-surface-enter relative overflow-hidden p-6 md:p-7">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.13),transparent_36%),radial-gradient(circle_at_84%_20%,rgba(215,90,45,0.11),transparent_24%)]" />
        <div className="relative flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-3xl">
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.detail.pageEyebrow")}</p>
            <h2 className="mt-3 text-3xl font-semibold text-ink">{sourceTitle(source)}</h2>
            <p className="mt-3 text-sm leading-7 text-[#596270]">{sourceRecovery?.impact_summary || sourceSubtitle(source)}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Badge tone="info">{formatStatusLabel(source.provider)}</Badge>
              <Badge tone={source.is_active ? "approved" : "info"}>{source.is_active ? translate("sources.detail.active") : translate("sources.detail.archived")}</Badge>
              <Badge tone="info">{productPhaseLabel(sourceProductPhase)}</Badge>
              <Badge tone={trustStateTone(sourceRecovery?.trust_state)}>{trustStateLabel(sourceRecovery?.trust_state)}</Badge>
            </div>
            {sourceRecovery?.next_action_label ? (
              <p className="mt-4 text-sm text-[#314051]">{translate("sources.detail.nextStep", { label: sourceRecovery.next_action_label })}</p>
            ) : null}
          </div>
          <div className="flex flex-wrap items-start gap-2 xl:max-w-[420px] xl:justify-end">
            {sourceProductPhase === "needs_initial_review" ? (
              <Button asChild size="sm">
                <Link href={withBasePath(basePath, "/initial-review")}>{translate("sources.detail.openInitialReview")}</Link>
              </Button>
            ) : sourceRecovery?.next_action === "reconnect_gmail" && source.provider === "gmail" ? (
              <Button size="sm" onClick={() => void reconnectSource()} disabled={busyReconnect}>
                <ExternalLink className="mr-2 h-4 w-4" />
                {busyReconnect ? translate("sources.detail.redirecting") : sourceRecovery.next_action_label}
              </Button>
            ) : sourceRecovery?.next_action === "update_ics" && source.provider === "ics" ? (
              <Button asChild size="sm">
                <Link href={connectHref(basePath, source.provider)}>{sourceRecovery.next_action_label}</Link>
              </Button>
            ) : (
              <Button size="sm" onClick={() => void runSync()} disabled={busySync || !source.is_active}>
                <RefreshCw className="mr-2 h-4 w-4" />
                {busySync ? translate("sources.detail.running") : sourceRecovery?.next_action === "retry_sync" ? sourceRecovery.next_action_label : translate("sources.detail.runSync")}
              </Button>
            )}
            {source.provider === "gmail" ? (
              sourceRecovery?.next_action === "reconnect_gmail" ? (
                <Button asChild size="sm" variant="soft">
                  <Link href={withBasePath(basePath, `/sources/${sourceId}`)}>{translate("sources.openDetails")}</Link>
                </Button>
              ) : (
                <Button size="sm" variant="soft" onClick={() => void reconnectSource()} disabled={busyReconnect}>
                  <ExternalLink className="mr-2 h-4 w-4" />
                  {busyReconnect ? translate("sources.detail.redirecting") : needsReconnect ? sourceRecovery?.next_action_label || translate("sources.reconnectGmail") : translate("sources.detail.openGmailConnection")}
                </Button>
              )
            ) : (
              sourceRecovery?.next_action === "update_ics" ? (
                <Button asChild size="sm" variant="soft">
                  <Link href={withBasePath(basePath, `/sources/${sourceId}`)}>{translate("sources.openDetails")}</Link>
                </Button>
              ) : (
                <Button asChild size="sm" variant="soft">
                  <Link href={connectHref(basePath, source.provider)}>{translate("sources.detail.openConnectionFlow")}</Link>
                </Button>
              )
            )}
            {source.is_active ? (
              <Button size="sm" variant="ghost" className="border border-line/80 bg-white/70" onClick={() => void archiveSource()} disabled={busyArchive}>
                <Trash2 className="mr-2 h-4 w-4" />
                {busyArchive ? translate("sources.archiving") : translate("sources.archive")}
              </Button>
            ) : (
              <Button size="sm" variant="ghost" className="border border-line/80 bg-white/70" onClick={() => void reactivateSource()} disabled={busyReactivate}>
                <ArchiveRestore className="mr-2 h-4 w-4" />
                {busyReactivate ? translate("sources.reactivating") : translate("sources.reactivate")}
              </Button>
            )}
          </div>
        </div>
      </Card>

      {banner ? (
        <Card className={banner.tone === "error" ? "border-[#efc4b5] bg-[#fff3ef] p-4" : "border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] p-4"}>
          <p className="text-sm text-[#314051]">{banner.text}</p>
        </Card>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="animate-surface-enter p-5">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.detail.connection")}</p>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {usageFact(translate("sources.detail.provider"), formatStatusLabel(source.provider))}
            {usageFact(translate("sources.detail.displayName"), source.display_name || sourceTitle(source))}
            {usageFact(translate("sources.detail.account"), source.oauth_account_email || translate("sources.detail.notApplicable"))}
            {usageFact(translate("sources.detail.lifecycle"), formatStatusLabel(source.lifecycle_state || (source.is_active ? "active" : "archived")))}
            {usageFact(translate("sources.detail.lastPolled"), formatDateTime(source.last_polled_at, translate("sources.detail.never")))}
            {usageFact(translate("sources.detail.nextPoll"), formatDateTime(source.next_poll_at, translate("sources.detail.notScheduled")))}
          </div>
        </Card>

        <Card className="animate-surface-enter p-5">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.detail.currentPosture")}</p>
          {observability.loading && !observability.data ? (
            <PanelLoadingPlaceholder rows={2} className="mt-4 p-4" />
          ) : observability.error && !observability.data ? (
            <div className="mt-4 rounded-[1.15rem] border border-[#efc4b5] bg-[#fff3ef] p-4 text-sm text-[#7f3d2a]">
              {`${translate("sources.detail.postureLoadFailed")} ${observability.error}`}
            </div>
          ) : (
            <div className="mt-4 rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-ink">{sourceRecovery?.impact_summary || translate("sources.detail.recoveryUnavailable")}</p>
                  <p className="mt-2 text-sm text-[#596270]">{productPhaseLabel(sourceProductPhase)} · {trustStateLabel(sourceRecovery?.trust_state)}</p>
                </div>
                <Badge tone={trustStateTone(sourceRecovery?.trust_state)}>{trustStateLabel(sourceRecovery?.trust_state)}</Badge>
              </div>
              {sourceRecovery ? (
                <div className="mt-4 grid gap-3 md:grid-cols-3">
                  {usageFact(translate("sources.detail.nextAction"), sourceRecovery.next_action_label)}
                  {usageFact(translate("sources.detail.lastGoodSync"), formatDateTime(sourceRecovery.last_good_sync_at, translate("sources.detail.notRecorded")))}
                  {usageFact(translate("sources.detail.degradedSince"), formatDateTime(sourceRecovery.degraded_since, translate("sources.detail.notDegraded")))}
                </div>
              ) : null}
              {sourceRecovery?.recovery_steps?.length ? (
                <div className="mt-4 rounded-[1rem] border border-line/80 bg-white/75 p-4">
                  <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("sources.detail.recoverySteps")}</p>
                  <div className="mt-3 space-y-2 text-sm text-[#314051]">
                    {sourceRecovery.recovery_steps.map((step) => (
                      <p key={step}>{step}</p>
                    ))}
                  </div>
                </div>
              ) : null}
              {activeSync ? (
                <>
                  <div className="mt-4 grid gap-3 md:grid-cols-3">
                    {usageFact(translate("sources.detail.currentRun"), formatStatusLabel(activeSync.status))}
                    {usageFact(translate("sources.observability.stage"), formatStatusLabel(activeSync.substage || activeSync.stage, translate("sources.detail.noStageSample")))}
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

        <Card className="animate-surface-enter p-5">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.detail.bootstrap")}</p>
          {observability.loading && !observability.data ? (
            <PanelLoadingPlaceholder rows={2} className="mt-4 p-4" />
          ) : observability.error && !observability.data ? (
            <div className="mt-4 rounded-[1.15rem] border border-[#efc4b5] bg-[#fff3ef] p-4 text-sm text-[#7f3d2a]">
              {`${translate("sources.detail.postureLoadFailed")} ${observability.error}`}
            </div>
          ) : (
            <>
              <div className="mt-4">
                <SyncRunCard title={translate("sources.detail.bootstrapRun")} sync={bootstrap} />
              </div>
              <div className="mt-4 rounded-[1rem] border border-line/80 bg-white/75 p-4">
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

        <Card className="animate-surface-enter p-5">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.detail.replayHistory")}</p>
          {history.loading && !history.data ? (
            <PanelLoadingPlaceholder rows={2} className="mt-4 p-4" />
          ) : history.error && !history.data ? (
            <div className="mt-4 rounded-[1.15rem] border border-[#efc4b5] bg-[#fff3ef] p-4 text-sm text-[#7f3d2a]">
              {`${translate("sources.detail.historyLoadFailed")} ${history.error}`}
            </div>
          ) : (
            <div className="mt-4 space-y-3">
              <SyncRunCard title={translate("sources.detail.latestReplay")} sync={latestReplay} />
              {(history.data?.items || []).slice(0, 6).map((item) => (
                <div key={item.request_id} className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-ink">{formatStatusLabel(item.status)} replay</p>
                      <p className="mt-1 text-sm text-[#596270]">{formatDateTime(item.updated_at)} · {formatStatusLabel(item.substage || item.stage, translate("sources.detail.noStageSample"))}</p>
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
    </div>
  );
}
