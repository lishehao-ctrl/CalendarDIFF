"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, CalendarSync, ExternalLink, Trash2 } from "lucide-react";
import { SourceRecoveryAgentCard } from "@/components/source-recovery-agent-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState } from "@/components/data-states";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";
import { WorkbenchLoadingShell } from "@/components/workbench-loading-shell";
import { SourceSyncProgress } from "@/components/source-sync-progress";
import { withBasePath } from "@/lib/demo-mode";
import { translate } from "@/lib/i18n/runtime";
import { buildSourceObservabilityViews } from "@/lib/source-observability";
import { invalidateSourceCaches } from "@/lib/source-cache";
import { deleteSource, getSyncRequest, listSources, sourceListCacheKey, updateSource } from "@/lib/api/sources";
import { useResponsiveTier } from "@/lib/use-responsive-tier";
import { useApiResource } from "@/lib/use-api-resource";
import { formatDateTime } from "@/lib/presenters";
import { workbenchPanelClassName, workbenchStateSurfaceClassName, workbenchSupportPanelClassName } from "@/lib/workbench-styles";
import type { SourceRow, SyncStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const DeferredSourceObservabilitySections = dynamic(
  () => import("@/components/source-observability-sections").then((mod) => mod.SourceObservabilitySections),
  {
    loading: () => <PanelLoadingPlaceholder rows={2} className="mt-4 p-4" />,
  },
);

export function CanvasIcsSetupPanel({ basePath = "" }: { basePath?: string }) {
  const { isTabletWide, isDesktop } = useResponsiveTier();
  const { data, loading, error, refresh } = useApiResource<SourceRow[]>(() => listSources({ status: "all" }), [], null, {
    cacheKey: sourceListCacheKey("all"),
  });
  const [syncDetail, setSyncDetail] = useState<SyncStatus | null>(null);
  const [canvasIcsUrl, setCanvasIcsUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [busyArchive, setBusyArchive] = useState(false);
  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);

  const source = useMemo(() => (data || []).find((row) => row.provider === "ics") || null, [data]);

  useEffect(() => {
    if (!source || (source.runtime_state !== "running" && source.runtime_state !== "queued" && source.runtime_state !== "rebind_pending" && !source.sync_progress)) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void refresh({ background: true, force: true });
    }, 2000);
    return () => window.clearInterval(intervalId);
  }, [refresh, source]);

  useEffect(() => {
    if (!source) {
      return;
    }
    setCanvasIcsUrl("");
  }, [source]);

  useEffect(() => {
    let cancelled = false;
    if (!source?.active_request_id) {
      setSyncDetail(null);
      return;
    }
    void getSyncRequest(source.active_request_id)
      .then((payload) => {
        if (!cancelled) setSyncDetail(payload);
      })
      .catch(() => {
        if (!cancelled) setSyncDetail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [source?.active_request_id]);

  const observability = useMemo(() => {
    if (!source) return null;
    return buildSourceObservabilityViews([source], {
      previewMode: basePath === "/preview",
      syncStatusesBySource: syncDetail ? { [source.source_id]: syncDetail } : {},
    })[0];
  }, [basePath, source, syncDetail]);
  const showSupportColumn = isTabletWide || isDesktop;

  async function save() {
    const normalizedUrl = canvasIcsUrl.trim();
    if (!normalizedUrl) return;
    if (!source) {
      setBanner({
        tone: "error",
        text: translate("sourceConnect.canvasPanel.connectMissing"),
      });
      return;
    }
    setSubmitting(true);
    setBanner(null);
    try {
      await updateSource(source.source_id, { is_active: true, secrets: { url: normalizedUrl } });
      invalidateSourceCaches(source.source_id);
      setBanner({ tone: "info", text: source.is_active ? translate("sourceConnect.canvasPanel.saveSuccess") : translate("sourceConnect.canvasPanel.saveReactivatedSuccess") });
      setCanvasIcsUrl("");
      await refresh({ force: true });
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("sourceConnect.canvasPanel.saveFailed") });
    } finally {
      setSubmitting(false);
    }
  }

  async function archive() {
    if (!source) return;
    const confirmed = window.confirm(translate("sourceConnect.canvasPanel.archiveConfirm"));
    if (!confirmed) return;
    setBusyArchive(true);
    setBanner(null);
    try {
      await deleteSource(source.source_id);
      invalidateSourceCaches(source.source_id);
      setBanner({ tone: "info", text: translate("sourceConnect.canvasPanel.archiveSuccess") });
      await refresh({ force: true });
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("sourceConnect.canvasPanel.archiveFailed") });
    } finally {
      setBusyArchive(false);
    }
  }

  if (loading) return <WorkbenchLoadingShell variant="source-connect" />;
  if (error) return <ErrorState message={error} />;
  if (!data) return <EmptyState title={translate("sourceConnect.canvasPanel.stateUnavailableTitle")} description={translate("sourceConnect.canvasPanel.stateUnavailableDescription")} />;

  return (
    <div className="space-y-5">
      <Card className="p-6 md:p-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">{translate("sourceConnect.canvasPanel.setupEyebrow")}</p>
            <h3 className="mt-3 text-2xl font-semibold">{translate("sourceConnect.canvasPanel.title")}</h3>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-[#596270]">
              {translate("sourceConnect.canvasPanel.summary")}
            </p>
          </div>
          <Button asChild size="sm" variant="ghost">
            <Link href={withBasePath(basePath, "/sources")}>
              <ArrowLeft className="mr-2 h-4 w-4" />
              {translate("sourceConnect.backToSources")}
            </Link>
          </Button>
        </div>

        {banner ? <div className={workbenchStateSurfaceClassName(banner.tone === "error" ? "error" : "info", "mt-5 px-4 py-3 text-sm text-[#314051]")}>{banner.text}</div> : null}

        {observability ? (
          <Card className={workbenchPanelClassName("secondary", "mt-6 p-5")}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sourceConnect.postureTitle")}</p>
                <h4 className="mt-2 text-lg font-semibold text-ink">{translate("sourceConnect.postureSummary")}</h4>
              </div>
              <Badge tone={source?.is_active ? "approved" : "info"}>{source?.is_active ? translate("sourceConnect.gmailPanel.connected") : translate("sourceConnect.gmailPanel.archived")}</Badge>
            </div>
            <DeferredSourceObservabilitySections observability={observability} className="mt-4" />
          </Card>
        ) : null}

        <div className={cn("mt-6 grid gap-5", showSupportColumn ? "lg:grid-cols-[minmax(0,1fr)_320px]" : "")}>
          <div className="space-y-5">
          <Card className={workbenchPanelClassName("secondary", "p-5")}>
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(31,94,255,0.1)] text-cobalt">
                <CalendarSync className="h-5 w-5" />
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sourceConnect.canvasPanel.currentConnection")}</p>
                <h4 className="mt-2 text-lg font-semibold text-ink">{source ? translate("sourceConnect.canvasPanel.configured") : translate("sourceConnect.canvasPanel.missing")}</h4>
              </div>
            </div>
            <div className={workbenchSupportPanelClassName("default", "mt-5 p-4 text-sm text-[#314051]")}>
              <p>{translate("sourceConnect.canvasPanel.status")}: {source ? (source.is_active ? translate("sourceConnect.gmailPanel.connected") : translate("sourceConnect.gmailPanel.archived")) : translate("sourceConnect.gmailPanel.notConnected")}</p>
              <p className="mt-2">{translate("sourceConnect.canvasPanel.source")}: {source ? `#${source.source_id}` : translate("sourceConnect.canvasPanel.sourceWillBeCreated")}</p>
              <p className="mt-2">{translate("sourceConnect.canvasPanel.lastPolled")}: {formatDateTime(source?.last_polled_at, translate("sources.detail.never"))}</p>
            </div>
            <SourceSyncProgress className="mt-4" progress={source?.sync_progress} stableLabel={translate("sourceConnect.canvasPanel.syncingLabel")} />
            {source ? (
              <div className="mt-5">
                <Button variant="ghost" onClick={() => void archive()} disabled={busyArchive}>
                  <Trash2 className="mr-2 h-4 w-4" />
                  {busyArchive ? translate("sourceConnect.canvasPanel.archiving") : translate("sourceConnect.canvasPanel.archiveLink")}
                </Button>
              </div>
            ) : null}
          </Card>

          <div className="space-y-5">
            <Card className={workbenchPanelClassName("secondary", "p-5")}>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="approved">UCSD Canvas</Badge>
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sourceConnect.canvasPanel.getLinkEyebrow")}</p>
              </div>
              <p className="mt-3 text-base font-medium text-ink">{translate("sourceConnect.canvasPanel.getLinkTitle")}</p>
              <p className="mt-2 leading-6 text-[#596270]">
                {translate("sourceConnect.canvasPanel.getLinkSummary")}
              </p>
              <div className="mt-4 grid gap-3 md:grid-cols-3">
                <div className={workbenchSupportPanelClassName("default", "p-3")}><p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("common.labels.step", { step: 1 })}</p><p className="mt-2 font-medium text-ink">{translate("sourceConnect.canvasPanel.step1")}</p><p className="mt-1 text-sm leading-6 text-[#596270]">{translate("sourceConnect.canvasPanel.step1Summary")}</p></div>
                <div className={workbenchSupportPanelClassName("default", "p-3")}><p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("common.labels.step", { step: 2 })}</p><p className="mt-2 font-medium text-ink">{translate("sourceConnect.canvasPanel.step2")}</p><p className="mt-1 text-sm leading-6 text-[#596270]">{translate("sourceConnect.canvasPanel.step2Summary")}</p></div>
                <div className={workbenchSupportPanelClassName("default", "p-3")}><p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("common.labels.step", { step: 3 })}</p><p className="mt-2 font-medium text-ink">{translate("sourceConnect.canvasPanel.step3")}</p><p className="mt-1 text-sm leading-6 text-[#596270]">{translate("sourceConnect.canvasPanel.step3Summary")}</p></div>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <a href="https://canvas.ucsd.edu/calendar" target="_blank" rel="noreferrer noopener" className="inline-flex h-10 items-center justify-center gap-2 rounded-full bg-cobalt-soft px-4 text-sm font-medium text-cobalt transition-all duration-200 hover:bg-[rgba(31,94,255,0.16)]">
                  <span>{translate("sourceConnect.canvasPanel.openCanvas")}</span>
                  <ExternalLink className="h-4 w-4" />
                </a>
                <p className="text-xs text-[#6d7885]">{translate("sourceConnect.canvasPanel.openCanvasHint")}</p>
              </div>
            </Card>
            <Card className={workbenchPanelClassName("secondary", "p-5")}>
              <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="canvas-ics-url">{translate("sourceConnect.canvasPanel.urlLabel")}</label>
              <Input id="canvas-ics-url" placeholder="https://canvas.example.edu/feeds/calendars/user_12345.ics" value={canvasIcsUrl} onChange={(event) => setCanvasIcsUrl(event.target.value)} />
              <p className="mt-2 text-xs leading-5 text-[#6d7885]">{translate("sourceConnect.canvasPanel.urlHint")}</p>
              {!source ? (
                <div className={workbenchSupportPanelClassName("quiet", "mt-4 px-4 py-3 text-sm text-[#314051]")}>
                  {translate("sourceConnect.canvasPanel.missingSource")}
                </div>
              ) : null}
              <div className="mt-5">
                <Button className="w-full" disabled={submitting || !canvasIcsUrl.trim() || !source} onClick={() => void save()}>
                  {submitting ? translate("sourceConnect.canvasPanel.saving") : translate("sourceConnect.canvasPanel.updateLink")}
                </Button>
              </div>
            </Card>
          </div>
          </div>
          <div className="space-y-4">
            {source ? <SourceRecoveryAgentCard sourceId={source.source_id} basePath={basePath} /> : null}
          </div>
        </div>
      </Card>
    </div>
  );
}
