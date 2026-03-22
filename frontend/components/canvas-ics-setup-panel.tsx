"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, CalendarSync, ExternalLink, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { SourceObservabilitySections } from "@/components/source-observability-sections";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { SourceSyncProgress } from "@/components/source-sync-progress";
import { withBasePath } from "@/lib/demo-mode";
import { buildSourceObservabilityViews } from "@/lib/source-observability";
import { invalidateSourceCaches } from "@/lib/source-cache";
import { deleteSource, getSyncRequest, listSources, sourceListCacheKey, updateSource } from "@/lib/api/sources";
import { useApiResource } from "@/lib/use-api-resource";
import { formatDateTime } from "@/lib/presenters";
import type { SourceRow, SyncStatus } from "@/lib/types";

export function CanvasIcsSetupPanel({ basePath = "" }: { basePath?: string }) {
  const { data, loading, error, refresh } = useApiResource<SourceRow[]>(() => listSources({ status: "all" }), [], null, {
    cacheKey: sourceListCacheKey("all"),
    readCachedSnapshot: false,
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

  async function save() {
    const normalizedUrl = canvasIcsUrl.trim();
    if (!normalizedUrl) return;
    if (!source) {
      setBanner({
        tone: "error",
        text: "Canvas ICS is created during required setup. Go back to onboarding if this workspace no longer has its Canvas source.",
      });
      return;
    }
    setSubmitting(true);
    setBanner(null);
    try {
      await updateSource(source.source_id, { is_active: true, secrets: { url: normalizedUrl } });
      invalidateSourceCaches(source.source_id);
      setBanner({ tone: "info", text: source.is_active ? "Canvas ICS link updated." : "Canvas ICS link reactivated and updated." });
      setCanvasIcsUrl("");
      await refresh({ force: true });
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to save Canvas ICS link" });
    } finally {
      setSubmitting(false);
    }
  }

  async function archive() {
    if (!source) return;
    const confirmed = window.confirm("Archive this Canvas ICS link?");
    if (!confirmed) return;
    setBusyArchive(true);
    setBanner(null);
    try {
      await deleteSource(source.source_id);
      invalidateSourceCaches(source.source_id);
      setBanner({ tone: "info", text: "Canvas ICS link archived." });
      await refresh({ force: true });
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to archive Canvas ICS link" });
    } finally {
      setBusyArchive(false);
    }
  }

  if (loading) return <LoadingState label="canvas ics setup" />;
  if (error) return <ErrorState message={error} />;
  if (!data) return <EmptyState title="Source state unavailable" description="Unable to load the current Canvas ICS configuration." />;

  return (
    <div className="space-y-5">
      <Card className="p-6 md:p-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Canvas ICS setup</p>
            <h3 className="mt-3 text-2xl font-semibold">Manage your Canvas calendar feed</h3>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-[#596270]">
              Connect or update the single Canvas ICS subscription used by this workspace.
            </p>
          </div>
          <Button asChild size="sm" variant="ghost">
            <Link href={withBasePath(basePath, "/sources")}>
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to Sources
            </Link>
          </Button>
        </div>

        {banner ? (
          <div className={banner.tone === "error" ? "mt-5 rounded-[1.15rem] border border-[#efc4b5] bg-[#fff3ef] px-4 py-3 text-sm text-[#7f3d2a]" : "mt-5 rounded-[1.15rem] border border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] px-4 py-3 text-sm text-[#314051]"}>
            {banner.text}
          </div>
        ) : null}

        {observability ? (
          <Card className="mt-6 bg-white/60 p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Source posture</p>
                <h4 className="mt-2 text-lg font-semibold text-ink">Bootstrap vs replay</h4>
              </div>
              <Badge tone={source?.is_active ? "approved" : "info"}>{source?.is_active ? "Connected" : "Archived"}</Badge>
            </div>
            <SourceObservabilitySections observability={observability} className="mt-4" />
          </Card>
        ) : null}

        <div className="mt-6 grid gap-5 xl:grid-cols-[1fr_0.95fr]">
          <Card className="bg-white/60 p-5">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(31,94,255,0.1)] text-cobalt">
                <CalendarSync className="h-5 w-5" />
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Current connection</p>
                <h4 className="mt-2 text-lg font-semibold text-ink">{source ? "Canvas ICS configured" : "No Canvas ICS yet"}</h4>
              </div>
            </div>
            <div className="mt-5 rounded-[1.15rem] border border-line/80 bg-white/70 p-4 text-sm text-[#314051]">
              <p>Status: {source ? (source.is_active ? "Connected" : "Archived") : "Not connected"}</p>
              <p className="mt-2">Source: {source ? `#${source.source_id}` : "Will be created on first save"}</p>
              <p className="mt-2">Last polled: {formatDateTime(source?.last_polled_at, "Never")}</p>
            </div>
            <SourceSyncProgress className="mt-4" progress={source?.sync_progress} stableLabel="Syncing Canvas source" />
            {source ? (
              <div className="mt-5">
                <Button variant="ghost" onClick={() => void archive()} disabled={busyArchive}>
                  <Trash2 className="mr-2 h-4 w-4" />
                  {busyArchive ? "Archiving..." : "Archive link"}
                </Button>
              </div>
            ) : null}
          </Card>

          <div className="space-y-5">
            <Card className="bg-white/60 p-5">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="approved">UCSD Canvas</Badge>
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Get your ICS link</p>
              </div>
              <p className="mt-3 text-base font-medium text-ink">Grab your personal calendar feed, then paste it here.</p>
              <p className="mt-2 leading-6 text-[#596270]">
                This workspace only needs one Canvas ICS subscription link. Canvas gives you that link from the Calendar page.
              </p>
              <div className="mt-4 grid gap-3 md:grid-cols-3">
                <div className="rounded-[1rem] border border-line/70 bg-white/75 p-3"><p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Step 1</p><p className="mt-2 font-medium text-ink">Open Canvas Calendar</p><p className="mt-1 text-sm leading-6 text-[#596270]">Go to your UCSD Canvas Calendar page in a new tab.</p></div>
                <div className="rounded-[1rem] border border-line/70 bg-white/75 p-3"><p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Step 2</p><p className="mt-2 font-medium text-ink">Copy the feed URL</p><p className="mt-1 text-sm leading-6 text-[#596270]">Copy your personal calendar feed / ICS subscription link from Canvas.</p></div>
                <div className="rounded-[1rem] border border-line/70 bg-white/75 p-3"><p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Step 3</p><p className="mt-2 font-medium text-ink">Paste and connect</p><p className="mt-1 text-sm leading-6 text-[#596270]">Paste that full URL below and save it to update this workspace.</p></div>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <a href="https://canvas.ucsd.edu/calendar" target="_blank" rel="noreferrer noopener" className="inline-flex h-10 items-center justify-center gap-2 rounded-full bg-cobalt-soft px-4 text-sm font-medium text-cobalt transition-all duration-200 hover:bg-[rgba(31,94,255,0.16)]">
                  <span>Open Canvas Calendar</span>
                  <ExternalLink className="h-4 w-4" />
                </a>
                <p className="text-xs text-[#6d7885]">Opens `canvas.ucsd.edu/calendar` in a new tab so you can come back and paste the link.</p>
              </div>
            </Card>
            <Card className="bg-white/60 p-5">
              <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="canvas-ics-url">Canvas ICS URL</label>
              <Input id="canvas-ics-url" placeholder="https://canvas.example.edu/feeds/calendars/user_12345.ics" value={canvasIcsUrl} onChange={(event) => setCanvasIcsUrl(event.target.value)} />
              <p className="mt-2 text-xs leading-5 text-[#6d7885]">Paste the full calendar subscription URL from Canvas here. Saving a new URL replaces the current Canvas ICS link for this workspace.</p>
              {!source ? (
                <div className="mt-4 rounded-[1rem] border border-line/80 bg-white/70 px-4 py-3 text-sm text-[#314051]">
                  This workspace does not currently have a Canvas source record. Re-run setup from{" "}
                  <Link href={withBasePath(basePath, "/onboarding")} className="font-medium text-cobalt underline-offset-4 hover:underline">
                    onboarding
                  </Link>{" "}
                  if you need to reconnect the required calendar intake.
                </div>
              ) : null}
              <div className="mt-5">
                <Button className="w-full" disabled={submitting || !canvasIcsUrl.trim() || !source} onClick={() => void save()}>
                  {submitting ? "Saving Canvas ICS..." : "Update Canvas ICS link"}
                </Button>
              </div>
            </Card>
          </div>
        </div>
      </Card>
    </div>
  );
}
