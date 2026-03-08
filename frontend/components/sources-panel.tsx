"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArchiveRestore, BellDot, CalendarSync, ChevronRight, Mailbox, RefreshCw, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { createSyncRequest, deleteSource as deleteSourceRequest, getSyncRequest, listSources, updateSource } from "@/lib/api/sources";
import { useApiResource } from "@/lib/use-api-resource";
import { formatDateTime, formatStatusLabel } from "@/lib/presenters";
import type { SourceRow, SyncStatus } from "@/lib/types";

const oauthQueryKeys = ["oauth_provider", "oauth_status", "source_id", "request_id", "message"] as const;

type Banner = {
  tone: "info" | "error";
  text: string;
} | null;

function syncTone(value: string | undefined) {
  if (!value) return "default";
  if (["queued", "running", "pending"].includes(value)) return "pending";
  if (["succeeded", "success"].includes(value)) return "approved";
  if (["failed", "error"].includes(value)) return "error";
  return "default";
}

function formatSourceTitle(source: SourceRow) {
  if (source.provider === "ics") {
    return "Canvas ICS";
  }
  return source.display_name || source.source_key;
}

function formatSourceSubtitle(source: SourceRow) {
  if (source.provider === "ics") {
    return "Student calendar feed";
  }
  return `${source.source_kind} source · key \`${source.source_key}\``;
}

function sourceSetupHref(provider: string) {
  if (provider === "ics") {
    return "/sources/connect/canvas-ics";
  }
  if (provider === "gmail") {
    return "/sources/connect/gmail";
  }
  return "/sources";
}

function SourceInventoryCard({
  source,
  syncLabel,
  busyDelete,
  busyReactivate,
  onSync,
  onDelete,
  onReactivate,
  archived = false,
}: {
  source: SourceRow;
  syncLabel?: string;
  busyDelete: number | null;
  busyReactivate: number | null;
  onSync?: (sourceId: number) => void;
  onDelete: (sourceId: number, provider: string) => void;
  onReactivate?: (sourceId: number) => void;
  archived?: boolean;
}) {
  const isGmail = source.provider === "gmail";
  const isCanvasIcs = source.provider === "ics";

  return (
    <Card className={archived ? "bg-white/40 p-5" : "overflow-hidden p-5"}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <h4 className="text-lg font-semibold">{formatSourceTitle(source)}</h4>
            <Badge tone={source.is_active ? "active" : "default"}>{source.provider}</Badge>
            {!archived ? <Badge tone={syncTone(syncLabel)}>{formatStatusLabel(syncLabel, "Idle")}</Badge> : null}
            {isGmail && source.oauth_connection_status ? (
              <Badge tone={source.oauth_connection_status === "connected" ? "approved" : "pending"}>
                {formatStatusLabel(source.oauth_connection_status)}
              </Badge>
            ) : null}
            {archived ? <Badge tone="info">Archived</Badge> : null}
          </div>
          <p className="text-sm text-[#596270]">{formatSourceSubtitle(source)}</p>
          {isGmail && source.oauth_account_email ? (
            <p className="text-sm text-[#314051]">Connected Gmail account: {source.oauth_account_email}</p>
          ) : null}
          {isCanvasIcs ? (
            <p className="text-sm text-[#314051]">Canvas ICS is the single student calendar link attached to this workspace.</p>
          ) : null}
          <div className="grid gap-2 text-sm text-[#314051] md:grid-cols-2">
            <p>Last polled: {formatDateTime(source.last_polled_at, "Never")}</p>
            <p>Next poll: {formatDateTime(source.next_poll_at, "Not scheduled")}</p>
            <p>Poll interval: {Math.round(source.poll_interval_seconds / 60)} min</p>
            <p>Status: {source.is_active ? "Active" : "Archived"}</p>
          </div>
          {source.last_error_message ? (
            <div className="rounded-[1.15rem] border border-[#efc4b5] bg-[#fff3ef] px-4 py-3 text-sm text-[#7f3d2a]">
              {source.last_error_message}
            </div>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!archived ? (
            <>
              <Button onClick={() => onSync?.(source.source_id)}>
                <RefreshCw className="mr-2 h-4 w-4" />
                Sync now
              </Button>
              <Button asChild variant="ghost">
                <Link href={sourceSetupHref(source.provider)}>
                  Manage
                  <ChevronRight className="ml-2 h-4 w-4" />
                </Link>
              </Button>
              <Button
                variant="ghost"
                onClick={() => onDelete(source.source_id, source.provider)}
                disabled={busyDelete === source.source_id}
              >
                <Trash2 className="mr-2 h-4 w-4" />
                {busyDelete === source.source_id ? "Archiving..." : isGmail ? "Disconnect mailbox" : isCanvasIcs ? "Archive link" : "Archive source"}
              </Button>
            </>
          ) : (
            <>
              <Button
                onClick={() => onReactivate?.(source.source_id)}
                disabled={busyReactivate === source.source_id}
              >
                <ArchiveRestore className="mr-2 h-4 w-4" />
                {busyReactivate === source.source_id ? "Reactivating..." : "Reactivate"}
              </Button>
              <Button asChild variant="ghost">
                <Link href={sourceSetupHref(source.provider)}>
                  Manage
                  <ChevronRight className="ml-2 h-4 w-4" />
                </Link>
              </Button>
            </>
          )}
        </div>
      </div>
    </Card>
  );
}

export function SourcesPanel() {
  const active = useApiResource<SourceRow[]>(() => listSources({ status: "active" }), []);
  const archived = useApiResource<SourceRow[]>(() => listSources({ status: "archived" }), []);
  const [activeSection, setActiveSection] = useState<"inventory" | "catalog" | "archived">("inventory");
  const [syncState, setSyncState] = useState<Record<number, string>>({});
  const [busyDelete, setBusyDelete] = useState<number | null>(null);
  const [busyReactivate, setBusyReactivate] = useState<number | null>(null);
  const [banner, setBanner] = useState<Banner>(null);
  const oauthQueryHandled = useRef(false);

  const activeSources = useMemo(() => active.data || [], [active.data]);
  const archivedSources = useMemo(() => archived.data || [], [archived.data]);
  const erroredCount = activeSources.filter((source) => Boolean(source.last_error_message)).length;

  const refreshAll = useCallback(async () => {
    await Promise.all([active.refresh(), archived.refresh()]);
  }, [active, archived]);

  const pollSyncRequest = useCallback(async (
    sourceId: number,
    requestId: string,
    options?: { successMessage?: string; failurePrefix?: string }
  ) => {
    setSyncState((prev) => ({ ...prev, [sourceId]: "queued" }));
    for (let attempt = 0; attempt < 15; attempt += 1) {
      const status = await getSyncRequest(requestId);
      const normalized = status.status.toLowerCase();
      setSyncState((prev) => ({ ...prev, [sourceId]: normalized }));
      if (status.status === "SUCCEEDED" || status.status === "FAILED") {
        if (status.status === "SUCCEEDED") {
          setBanner({ tone: "info", text: options?.successMessage || `Source #${sourceId} sync succeeded.` });
        }
        if (status.status === "FAILED") {
          const failure = status.error_message || status.connector_result?.error_message || options?.failurePrefix || `Source #${sourceId} sync failed.`;
          setBanner({ tone: "error", text: failure });
        }
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    await refreshAll();
  }, [refreshAll]);

  useEffect(() => {
    if (oauthQueryHandled.current) {
      return;
    }
    oauthQueryHandled.current = true;

    const url = new URL(window.location.href);
    const provider = url.searchParams.get("oauth_provider");
    const status = url.searchParams.get("oauth_status");
    const sourceIdRaw = url.searchParams.get("source_id");
    const requestId = url.searchParams.get("request_id");
    const message = url.searchParams.get("message");

    if (!provider || provider !== "gmail" || !status) {
      return;
    }

    const sourceId = sourceIdRaw ? Number(sourceIdRaw) : null;
    setBanner({
      tone: status === "success" ? "info" : "error",
      text: message || (status === "success" ? "Gmail connection succeeded." : "Gmail connection failed.")
    });

    for (const key of oauthQueryKeys) {
      url.searchParams.delete(key);
    }
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);

    void refreshAll();
    if (status === "success" && requestId && sourceId) {
      void pollSyncRequest(sourceId, requestId, {
        successMessage: "Gmail initial sync succeeded.",
        failurePrefix: "Gmail initial sync failed"
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
          : "Archive this source?"
    );
    if (!confirmed) {
      return;
    }

    setBusyDelete(sourceId);
    setBanner(null);
    try {
      await deleteSourceRequest(sourceId);
      setBanner({
        tone: "info",
        text: provider === "gmail" ? "Mailbox disconnected and archived." : provider === "ics" ? "Canvas ICS link archived." : "Source archived."
      });
      await refreshAll();
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
      await refreshAll();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to reactivate source" });
    } finally {
      setBusyReactivate(null);
    }
  }

  if (active.loading || archived.loading) return <LoadingState label="sources" />;
  if (active.error) return <ErrorState message={active.error} />;
  if (archived.error) return <ErrorState message={archived.error} />;

  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card className="p-5">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Connected sources</p>
          <p className="mt-3 text-3xl font-semibold">{activeSources.length}</p>
          <p className="mt-2 text-sm text-[#596270]">Currently active sources in this workspace.</p>
        </Card>
        <Card className="p-5">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Archived sources</p>
          <p className="mt-3 text-3xl font-semibold">{archivedSources.length}</p>
          <p className="mt-2 text-sm text-[#596270]">Disconnected or archived sources that can still be restored.</p>
        </Card>
        <Card className="p-5">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Errored sources</p>
          <p className="mt-3 text-3xl font-semibold">{erroredCount}</p>
          <p className="mt-2 text-sm text-[#596270]">Connected sources with a recorded connector or validation error.</p>
        </Card>
        <Card className="p-5">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Add source</p>
          <p className="mt-3 text-3xl font-semibold">2</p>
          <p className="mt-2 text-sm text-[#596270]">Current catalog entries available for this workspace.</p>
        </Card>
      </div>

      {banner ? (
        <Card className={banner.tone === "error" ? "border-[#efc4b5] bg-[#fff3ef] p-4" : "border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] p-4"}>
          <p className="text-sm text-[#314051]">{banner.text}</p>
        </Card>
      ) : null}

      <Card className="p-6 md:p-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Sources workspace</p>
            <h3 className="mt-3 text-2xl font-semibold">Manage connections</h3>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-[#596270]">
              Switch between live inventory, the add-source catalog, and archived connections without scrolling through every section at once.
            </p>
          </div>
          <Badge tone="info">Workspace</Badge>
        </div>

        <div className="mt-5 inline-flex flex-wrap gap-2 rounded-full border border-line/80 bg-white/60 p-2">
          <Button size="sm" variant={activeSection === "inventory" ? "primary" : "ghost"} onClick={() => setActiveSection("inventory")}>
            Live inventory ({activeSources.length})
          </Button>
          <Button size="sm" variant={activeSection === "catalog" ? "primary" : "ghost"} onClick={() => setActiveSection("catalog")}>
            Source catalog (2)
          </Button>
          <Button size="sm" variant={activeSection === "archived" ? "primary" : "ghost"} onClick={() => setActiveSection("archived")}>
            Recover previous connections ({archivedSources.length})
          </Button>
        </div>

        {activeSection === "inventory" ? (
          <div className="mt-5 space-y-4">
            {activeSources.length === 0 ? (
              <EmptyState title="No connected sources" description="Use Source Catalog to connect Canvas ICS or Gmail." />
            ) : (
              activeSources.map((source) => (
                <SourceInventoryCard
                  key={source.source_id}
                  source={source}
                  syncLabel={syncState[source.source_id]}
                  busyDelete={busyDelete}
                  busyReactivate={busyReactivate}
                  onSync={triggerSync}
                  onDelete={archiveSource}
                />
              ))
            )}
          </div>
        ) : null}

        {activeSection === "catalog" ? (
          <div className="mt-5 grid gap-4 lg:grid-cols-3">
            <Card className="bg-white/60 p-5">
              <div className="flex items-start gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(31,94,255,0.1)] text-cobalt">
                  <CalendarSync className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Canvas ICS</p>
                  <h4 className="mt-2 text-lg font-semibold text-ink">Student calendar feed</h4>
                  <p className="mt-2 text-sm leading-6 text-[#596270]">Open the dedicated setup flow to connect, update, or reconnect your Canvas subscription URL.</p>
                </div>
              </div>
              <div className="mt-5">
                <Button asChild>
                  <Link href="/sources/connect/canvas-ics">
                    Open Canvas setup
                    <ChevronRight className="ml-2 h-4 w-4" />
                  </Link>
                </Button>
              </div>
            </Card>
            <Card className="bg-white/60 p-5">
              <div className="flex items-start gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(215,90,45,0.12)] text-ember">
                  <Mailbox className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Gmail</p>
                  <h4 className="mt-2 text-lg font-semibold text-ink">OAuth mailbox</h4>
                  <p className="mt-2 text-sm leading-6 text-[#596270]">Open the Gmail setup flow to connect, reconnect, or disconnect the single mailbox used by this workspace.</p>
                </div>
              </div>
              <div className="mt-5">
                <Button asChild>
                  <Link href="/sources/connect/gmail">
                    Open Gmail setup
                    <ChevronRight className="ml-2 h-4 w-4" />
                  </Link>
                </Button>
              </div>
            </Card>
            <Card className="bg-white/60 p-5">
              <div className="flex items-start gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(20,32,44,0.08)] text-ink">
                  <BellDot className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">More soon</p>
                  <h4 className="mt-2 text-lg font-semibold text-ink">Additional sources</h4>
                  <p className="mt-2 text-sm leading-6 text-[#596270]">This catalog is designed to scale as more source types are added in future iterations.</p>
                </div>
              </div>
            </Card>
          </div>
        ) : null}

        {activeSection === "archived" ? (
          <div className="mt-5 space-y-4">
            {archivedSources.length === 0 ? (
              <EmptyState title="No archived sources" description="Archived sources will appear here after you disconnect or archive them." />
            ) : (
              archivedSources.map((source) => (
                <SourceInventoryCard
                  key={source.source_id}
                  source={source}
                  busyDelete={busyDelete}
                  busyReactivate={busyReactivate}
                  onDelete={archiveSource}
                  onReactivate={reactivateSource}
                  archived
                />
              ))
            )}
          </div>
        ) : null}
      </Card>
    </div>
  );
}
