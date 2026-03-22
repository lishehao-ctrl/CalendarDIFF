"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArchiveRestore, ExternalLink, RefreshCw, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
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
import { formatDateTime, formatStatusLabel } from "@/lib/presenters";
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
    return "Student calendar feed";
  }
  return source.oauth_account_email || "Mailbox connection";
}

function connectHref(basePath: string, provider: string) {
  return provider === "ics" ? withBasePath(basePath, "/sources/connect/canvas-ics") : withBasePath(basePath, "/sources/connect/gmail");
}

function productPhaseLabel(phase: SourceRow["source_product_phase"] | null | undefined) {
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
  const totalTokens = typeof usage.total_tokens === "number" ? usage.total_tokens.toLocaleString() : "No sample";
  const cachedTokens = typeof usage.cached_input_tokens === "number" ? usage.cached_input_tokens.toLocaleString() : "0";
  const latencyMs = typeof usage.latency_ms_total === "number" ? `${Math.round(usage.latency_ms_total)} ms` : "No sample";
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
          <p className="mt-2 text-sm font-medium text-ink">{sync ? formatStatusLabel(sync.status) : "No run yet"}</p>
        </div>
        {sync ? <Badge tone={sync.status === "FAILED" ? "error" : sync.status === "RUNNING" ? "pending" : "approved"}>{formatStatusLabel(sync.status)}</Badge> : null}
      </div>
      {sync ? (
        <>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {usageFact("Elapsed", formatElapsedMs(sync.elapsed_ms || null))}
            {usageFact("Stage", formatStatusLabel(sync.substage || sync.stage, "Not sampled"))}
            {usageFact("Updated", formatDateTime(sync.updated_at))}
          </div>
          {sync.progress ? <SourceSyncProgress className="mt-4" progress={sync.progress} /> : null}
          {usage ? (
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              {usageFact("Tokens", usage.totalTokens)}
              {usageFact("Cached input", usage.cachedTokens)}
              {usageFact("Latency", usage.latencyMs)}
            </div>
          ) : null}
          {sync.error_message ? <p className="mt-4 text-sm leading-6 text-[#7f3d2a]">{sync.error_message}</p> : null}
        </>
      ) : (
        <p className="mt-4 text-sm text-[#596270]">No sampled run is available yet.</p>
      )}
    </div>
  );
}

export function SourceDetailPanel({ sourceId, basePath = "" }: { sourceId: number; basePath?: string }) {
  const sources = useApiResource<SourceRow[]>(() => listSources({ status: "all" }), [], null, {
    cacheKey: sourceListCacheKey("all"),
    readCachedSnapshot: false,
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

  async function refreshAll(options?: { background?: boolean; force?: boolean }) {
    await Promise.all([
      sources.refresh({ background: options?.background, force: options?.force }),
      observability.refresh({ background: options?.background, force: options?.force }),
      history.refresh({ background: options?.background, force: options?.force }),
    ]);
  }

  async function runSync() {
    setBusySync(true);
    setBanner(null);
    try {
      await createSyncRequest(sourceId, { metadata: { kind: "ui_source_detail_sync" } });
      invalidateSourceCaches(sourceId);
      setBanner({ tone: "info", text: "Sync request queued." });
      await refreshAll({ force: true });
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to run sync." });
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
      setBanner({ tone: "info", text: "Source archived." });
      await refreshAll({ force: true });
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to archive source." });
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
      setBanner({ tone: "info", text: "Source reactivated." });
      await refreshAll({ force: true });
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to reactivate source." });
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
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to reconnect source." });
      setBusyReconnect(false);
    }
  }

  if (sources.loading || observability.loading || history.loading) {
    return <LoadingState label="source detail" />;
  }
  if (sources.error) return <ErrorState message={`Source detail failed to load. ${sources.error}`} />;
  if (observability.error) return <ErrorState message={`Source posture failed to load. ${observability.error}`} />;
  if (history.error) return <ErrorState message={`Source history failed to load. ${history.error}`} />;
  if (!source) {
    return <EmptyState title="Source not found" description="This source is unavailable in the current workspace." />;
  }

  const activeSync = observability.data?.active || null;
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
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Source detail</p>
            <h2 className="mt-3 text-3xl font-semibold text-ink">{sourceTitle(source)}</h2>
            <p className="mt-3 text-sm leading-7 text-[#596270]">{sourceRecovery?.impact_summary || sourceSubtitle(source)}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Badge tone="info">{formatStatusLabel(source.provider)}</Badge>
              <Badge tone={source.is_active ? "approved" : "info"}>{source.is_active ? "Active" : "Archived"}</Badge>
              <Badge tone="info">{productPhaseLabel(sourceProductPhase)}</Badge>
              <Badge tone={trustStateTone(sourceRecovery?.trust_state)}>{trustStateLabel(sourceRecovery?.trust_state)}</Badge>
            </div>
            {sourceRecovery?.next_action_label ? (
              <p className="mt-4 text-sm text-[#314051]">Next step: {sourceRecovery.next_action_label}</p>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            {sourceProductPhase === "needs_initial_review" ? (
              <Button asChild>
                <Link href={withBasePath(basePath, "/initial-review")}>Open Initial Review</Link>
              </Button>
            ) : sourceRecovery?.next_action === "reconnect_gmail" && source.provider === "gmail" ? (
              <Button onClick={() => void reconnectSource()} disabled={busyReconnect}>
                <ExternalLink className="mr-2 h-4 w-4" />
                {busyReconnect ? "Redirecting..." : sourceRecovery.next_action_label}
              </Button>
            ) : sourceRecovery?.next_action === "update_ics" && source.provider === "ics" ? (
              <Button asChild>
                <Link href={connectHref(basePath, source.provider)}>{sourceRecovery.next_action_label}</Link>
              </Button>
            ) : (
              <Button onClick={() => void runSync()} disabled={busySync || !source.is_active}>
                <RefreshCw className="mr-2 h-4 w-4" />
                {busySync ? "Running..." : sourceRecovery?.next_action === "retry_sync" ? sourceRecovery.next_action_label : "Run sync"}
              </Button>
            )}
            {source.provider === "gmail" ? (
              sourceRecovery?.next_action === "reconnect_gmail" ? (
                <Button asChild variant="ghost">
                  <Link href={withBasePath(basePath, `/sources/${sourceId}`)}>Open details</Link>
                </Button>
              ) : (
                <Button variant="ghost" onClick={() => void reconnectSource()} disabled={busyReconnect}>
                  <ExternalLink className="mr-2 h-4 w-4" />
                  {busyReconnect ? "Redirecting..." : needsReconnect ? sourceRecovery?.next_action_label || "Reconnect Gmail" : "Open Gmail connection"}
                </Button>
              )
            ) : (
              sourceRecovery?.next_action === "update_ics" ? (
                <Button asChild variant="ghost">
                  <Link href={withBasePath(basePath, `/sources/${sourceId}`)}>Open details</Link>
                </Button>
              ) : (
                <Button asChild variant="ghost">
                  <Link href={connectHref(basePath, source.provider)}>Open connection flow</Link>
                </Button>
              )
            )}
            {source.is_active ? (
              <Button variant="ghost" onClick={() => void archiveSource()} disabled={busyArchive}>
                <Trash2 className="mr-2 h-4 w-4" />
                {busyArchive ? "Archiving..." : "Archive"}
              </Button>
            ) : (
              <Button variant="ghost" onClick={() => void reactivateSource()} disabled={busyReactivate}>
                <ArchiveRestore className="mr-2 h-4 w-4" />
                {busyReactivate ? "Reactivating..." : "Reactivate"}
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
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Connection</p>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {usageFact("Provider", formatStatusLabel(source.provider))}
            {usageFact("Display name", source.display_name || sourceTitle(source))}
            {usageFact("Account", source.oauth_account_email || "Not applicable")}
            {usageFact("Lifecycle", formatStatusLabel(source.lifecycle_state || (source.is_active ? "active" : "archived")))}
            {usageFact("Last polled", formatDateTime(source.last_polled_at, "Never"))}
            {usageFact("Next poll", formatDateTime(source.next_poll_at, "Not scheduled"))}
          </div>
        </Card>

        <Card className="animate-surface-enter p-5">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Current Posture</p>
          <div className="mt-4 rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-sm font-medium text-ink">{sourceRecovery?.impact_summary || "Recovery posture is not available yet."}</p>
                <p className="mt-2 text-sm text-[#596270]">{productPhaseLabel(sourceProductPhase)} · {trustStateLabel(sourceRecovery?.trust_state)}</p>
              </div>
              <Badge tone={trustStateTone(sourceRecovery?.trust_state)}>{trustStateLabel(sourceRecovery?.trust_state)}</Badge>
            </div>
            {sourceRecovery ? (
              <div className="mt-4 grid gap-3 md:grid-cols-3">
                {usageFact("Next action", sourceRecovery.next_action_label)}
                {usageFact("Last good sync", formatDateTime(sourceRecovery.last_good_sync_at, "Not recorded"))}
                {usageFact("Degraded since", formatDateTime(sourceRecovery.degraded_since, "Not degraded"))}
              </div>
            ) : null}
            {sourceRecovery?.recovery_steps?.length ? (
              <div className="mt-4 rounded-[1rem] border border-line/80 bg-white/75 p-4">
                <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">Recovery steps</p>
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
                  {usageFact("Current run", formatStatusLabel(activeSync.status))}
                  {usageFact("Stage", formatStatusLabel(activeSync.substage || activeSync.stage, "Not sampled"))}
                  {usageFact("Updated", formatDateTime(activeSync.updated_at))}
                </div>
                {activeSync.progress ? <SourceSyncProgress className="mt-4" progress={activeSync.progress} /> : null}
              </>
            ) : source.sync_progress ? (
              <SourceSyncProgress className="mt-4" progress={source.sync_progress} />
            ) : null}
          </div>
        </Card>

        <Card className="animate-surface-enter p-5">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Bootstrap</p>
          <div className="mt-4">
            <SyncRunCard title="Bootstrap run" sync={bootstrap} />
          </div>
          <div className="mt-4 rounded-[1rem] border border-line/80 bg-white/75 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">Import summary</p>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              {usageFact("Imported", String(bootstrapSummary?.imported_count || 0))}
              {usageFact("Needs review", String(bootstrapSummary?.review_required_count || 0))}
              {usageFact("Ignored", String(bootstrapSummary?.ignored_count || 0))}
              {usageFact("Conflicts", String(bootstrapSummary?.conflict_count || 0))}
              {usageFact("Records scanned", bootstrapRecordsCount !== null ? String(bootstrapRecordsCount) : "—")}
              {usageFact("Bootstrap state", formatStatusLabel(bootstrapSummary?.state, "Unknown"))}
            </div>
            {bootstrapSummary?.review_required_count ? (
              <p className="mt-4 text-xs leading-5 text-[#6d7885]">
                Baseline import still has items waiting in Initial Review. Clear them before treating this source as fully steady-state replay.
              </p>
            ) : null}
          </div>
        </Card>

        <Card className="animate-surface-enter p-5">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Replay History</p>
          <div className="mt-4 space-y-3">
            <SyncRunCard title="Latest replay" sync={latestReplay} />
            {(history.data?.items || []).slice(0, 6).map((item) => (
              <div key={item.request_id} className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-ink">{formatStatusLabel(item.status)} replay</p>
                    <p className="mt-1 text-sm text-[#596270]">{formatDateTime(item.updated_at)} · {formatStatusLabel(item.substage || item.stage, "No stage sample")}</p>
                  </div>
                  <Badge tone={item.status === "FAILED" ? "error" : item.status === "RUNNING" ? "pending" : "approved"}>
                    {formatElapsedMs(item.elapsed_ms || null)}
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
