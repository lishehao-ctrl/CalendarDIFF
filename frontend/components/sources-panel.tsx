"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CalendarSync, Mailbox, RefreshCw, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { backendFetch } from "@/lib/backend";
import { formatDateTime, formatStatusLabel } from "@/lib/presenters";
import type { SourceRow, SyncStatus } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

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

export function SourcesPanel() {
  const { data, loading, error, refresh } = useResource<SourceRow[]>("/sources");
  const [canvasIcsUrl, setCanvasIcsUrl] = useState("");
  const [syncState, setSyncState] = useState<Record<number, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [busyDelete, setBusyDelete] = useState<number | null>(null);
  const [gmailConnecting, setGmailConnecting] = useState(false);
  const [banner, setBanner] = useState<Banner>(null);
  const oauthQueryHandled = useRef(false);

  const sources = useMemo(() => data || [], [data]);
  const activeCount = sources.filter((source) => source.is_active).length;
  const erroredCount = sources.filter((source) => Boolean(source.last_error_message)).length;
  const gmailSource = useMemo(() => sources.find((source) => source.provider === "gmail") || null, [sources]);
  const canvasIcsSource = useMemo(() => sources.find((source) => source.provider === "ics") || null, [sources]);
  const gmailConnected = gmailSource?.oauth_connection_status === "connected";
  const canvasIcsConnected = Boolean(canvasIcsSource?.is_active);

  const pollSyncRequest = useCallback(async (
    sourceId: number,
    requestId: string,
    options?: { successMessage?: string; failurePrefix?: string }
  ) => {
    setSyncState((prev) => ({ ...prev, [sourceId]: "queued" }));
    for (let attempt = 0; attempt < 15; attempt += 1) {
      const status = await backendFetch<SyncStatus>(`/sync-requests/${requestId}`);
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
    await refresh();
  }, [refresh]);

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

    void refresh();
    if (status === "success" && requestId && sourceId) {
      void pollSyncRequest(sourceId, requestId, {
        successMessage: "Gmail initial sync succeeded.",
        failurePrefix: "Gmail initial sync failed"
      });
    }
  }, [pollSyncRequest, refresh]);

  async function createOrUpdateCanvasIcsSource() {
    const normalizedUrl = canvasIcsUrl.trim();
    if (!normalizedUrl) {
      return;
    }

    setSubmitting(true);
    setBanner(null);
    try {
      const existing = canvasIcsSource || await findExistingSource("ics");
      if (existing) {
        await backendFetch<SourceRow>(`/sources/${existing.source_id}`, {
          method: "PATCH",
          body: JSON.stringify({
            is_active: true,
            secrets: { url: normalizedUrl }
          })
        });
        setBanner({ tone: "info", text: "Canvas ICS link updated for this workspace." });
      } else {
        try {
          await backendFetch<SourceRow>("/sources", {
            method: "POST",
            body: JSON.stringify({
              source_kind: "calendar",
              provider: "ics",
              config: {},
              secrets: { url: normalizedUrl }
            })
          });
          setBanner({ tone: "info", text: "Canvas ICS link connected. You can trigger a manual sync immediately." });
        } catch (err) {
          const recovered = await findExistingSource("ics");
          if (!recovered) {
            throw err;
          }
          await backendFetch<SourceRow>(`/sources/${recovered.source_id}`, {
            method: "PATCH",
            body: JSON.stringify({
              is_active: true,
              secrets: { url: normalizedUrl }
            })
          });
          setBanner({ tone: "info", text: "Canvas ICS link updated for this workspace." });
        }
      }
      setCanvasIcsUrl("");
      await refresh();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to save Canvas ICS link" });
    } finally {
      setSubmitting(false);
    }
  }

  async function deleteSource(sourceId: number, provider: string) {
    const confirmed = window.confirm(
      provider === "gmail"
        ? "Disconnect this Gmail source from the workspace?"
        : provider === "ics"
          ? "Remove this Canvas ICS link from the workspace?"
          : "Delete this source from the workspace?"
    );
    if (!confirmed) {
      return;
    }

    setBusyDelete(sourceId);
    setBanner(null);
    try {
      await backendFetch(`/sources/${sourceId}`, { method: "DELETE" });
      setBanner({
        tone: "info",
        text: provider === "gmail"
          ? "Gmail source disconnected."
          : provider === "ics"
            ? "Canvas ICS link removed."
            : `Source #${sourceId} deleted.`
      });
      await refresh();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to delete source" });
    } finally {
      setBusyDelete(null);
    }
  }

  async function triggerSync(sourceId: number) {
    setBanner(null);
    try {
      const created = await backendFetch<{ request_id: string }>(`/sources/${sourceId}/sync-requests`, {
        method: "POST",
        body: JSON.stringify({ metadata: { kind: "ui_manual_sync" } })
      });
      await pollSyncRequest(sourceId, created.request_id);
    } catch (err) {
      const text = err instanceof Error ? err.message : "Sync failed";
      setSyncState((prev) => ({ ...prev, [sourceId]: "failed" }));
      setBanner({ tone: "error", text });
    }
  }

  async function connectGmail() {
    setGmailConnecting(true);
    setBanner(null);
    try {
      const source = await createOrReuseGmailSource();
      const session = await backendFetch<{ authorization_url: string }>(`/sources/${source.source_id}/oauth-sessions`, {
        method: "POST",
        body: JSON.stringify({ provider: "gmail" })
      });
      window.location.assign(session.authorization_url);
    } catch (err) {
      setGmailConnecting(false);
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to start Gmail OAuth" });
    }
  }

  async function createOrReuseGmailSource(): Promise<SourceRow> {
    if (gmailSource) {
      return gmailSource;
    }

    try {
      const created = await backendFetch<SourceRow>("/sources", {
        method: "POST",
        body: JSON.stringify({
          source_kind: "email",
          provider: "gmail",
          display_name: "Gmail Inbox",
          config: { label_id: "INBOX" },
          secrets: {}
        })
      });
      await refresh();
      return created;
    } catch (err) {
      const existing = await findExistingSource("gmail");
      if (existing) {
        return existing;
      }
      throw err;
    }
  }

  async function findExistingSource(provider: string): Promise<SourceRow | null> {
    const latestSources = await backendFetch<SourceRow[]>("/sources");
    const existing = latestSources.find((source) => source.provider === provider) || null;
    await refresh();
    return existing;
  }

  if (loading) return <LoadingState label="sources" />;
  if (error) return <ErrorState message={error} />;

  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card className="p-5">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Connected sources</p>
          <p className="mt-3 text-3xl font-semibold">{sources.length}</p>
          <p className="mt-2 text-sm text-[#596270]">Total source records attached to the current user.</p>
        </Card>
        <Card className="p-5">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Active sources</p>
          <p className="mt-3 text-3xl font-semibold">{activeCount}</p>
          <p className="mt-2 text-sm text-[#596270]">Sources that can accept manual or worker-driven sync requests.</p>
        </Card>
        <Card className="p-5">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Errored sources</p>
          <p className="mt-3 text-3xl font-semibold">{erroredCount}</p>
          <p className="mt-2 text-sm text-[#596270]">Sources with a recorded connector or validation failure.</p>
        </Card>
        <Card className="p-5">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Gmail connection</p>
          <p className="mt-3 text-3xl font-semibold">{gmailConnected ? "Live" : "Ready"}</p>
          <p className="mt-2 text-sm text-[#596270]">Single Gmail account, default label `INBOX`, browser-based Google OAuth.</p>
        </Card>
      </div>

      {banner ? (
        <Card className={banner.tone === "error" ? "border-[#efc4b5] bg-[#fff3ef] p-4" : "border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] p-4"}>
          <p className="text-sm text-[#314051]">{banner.text}</p>
        </Card>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[1.18fr_0.82fr]">
        <Card className="p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Live inventory</p>
              <h3 className="mt-3 text-2xl font-semibold">Connected sources</h3>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                Canvas ICS and Gmail are both visible here. Gmail is a single OAuth-backed mailbox, while Canvas ICS is the student calendar subscription for this workspace.
              </p>
            </div>
            <Badge tone="approved">API-backed</Badge>
          </div>

          <div className="mt-5 space-y-4">
            {sources.length === 0 ? (
              <EmptyState title="No sources yet" description="Connect your Canvas ICS link or Gmail to open the intake loop." />
            ) : (
              sources.map((source) => {
                const syncLabel = syncState[source.source_id];
                const isGmail = source.provider === "gmail";
                const isCanvasIcs = source.provider === "ics";
                return (
                  <Card key={source.source_id} className="overflow-hidden p-5">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div className="space-y-3">
                        <div className="flex flex-wrap items-center gap-3">
                          <h4 className="text-lg font-semibold">{formatSourceTitle(source)}</h4>
                          <Badge tone={source.is_active ? "active" : "default"}>{source.provider}</Badge>
                          <Badge tone={syncTone(syncLabel)}>{formatStatusLabel(syncLabel, "Idle")}</Badge>
                          {isGmail && source.oauth_connection_status ? (
                            <Badge tone={source.oauth_connection_status === "connected" ? "approved" : "pending"}>
                              {formatStatusLabel(source.oauth_connection_status)}
                            </Badge>
                          ) : null}
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
                          <p>Status: {source.is_active ? "Active" : "Inactive"}</p>
                        </div>
                        {source.last_error_message ? (
                          <div className="rounded-[1.15rem] border border-[#efc4b5] bg-[#fff3ef] px-4 py-3 text-sm text-[#7f3d2a]">
                            {source.last_error_message}
                          </div>
                        ) : null}
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Button onClick={() => void triggerSync(source.source_id)}>
                          <RefreshCw className="mr-2 h-4 w-4" />
                          Sync now
                        </Button>
                        <Button
                          variant="ghost"
                          onClick={() => void deleteSource(source.source_id, source.provider)}
                          disabled={busyDelete === source.source_id}
                        >
                          <Trash2 className="mr-2 h-4 w-4" />
                          {busyDelete === source.source_id ? "Removing..." : isGmail ? "Disconnect" : isCanvasIcs ? "Remove link" : "Delete"}
                        </Button>
                      </div>
                    </div>
                  </Card>
                );
              })
            )}
          </div>
        </Card>

        <div className="space-y-5">
          <Card className="p-6">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(31,94,255,0.1)] text-cobalt">
                <CalendarSync className="h-5 w-5" />
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Canvas ICS</p>
                <h3 className="mt-1 text-xl font-semibold">{canvasIcsSource ? "Update Canvas ICS link" : "Connect Canvas ICS"}</h3>
              </div>
            </div>
            <p className="mt-4 text-sm leading-6 text-[#596270]">
              A single Canvas ICS link represents the student calendar subscription for this workspace. Saving a new URL replaces the existing Canvas ICS link instead of creating another source.
            </p>
            <div className="mt-5 rounded-[1.25rem] border border-line bg-white/55 p-4 text-sm text-[#314051]">
              <p>Status: {canvasIcsConnected ? "Connected" : "Not connected"}</p>
              <p className="mt-2">Source: {canvasIcsSource ? `#${canvasIcsSource.source_id}` : "Will be created on first save"}</p>
              <p className="mt-2">Kind: Student calendar feed</p>
            </div>
            <div className="mt-5 space-y-4">
              <div>
                <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="canvas-ics-url">
                  Canvas ICS URL
                </label>
                <Input
                  id="canvas-ics-url"
                  placeholder="https://canvas.example.edu/feeds/calendars/user_12345.ics"
                  value={canvasIcsUrl}
                  onChange={(event) => setCanvasIcsUrl(event.target.value)}
                />
              </div>
              <Button className="w-full" disabled={submitting || !canvasIcsUrl.trim()} onClick={() => void createOrUpdateCanvasIcsSource()}>
                {submitting ? "Saving Canvas ICS..." : canvasIcsSource ? "Update Canvas ICS link" : "Connect Canvas ICS"}
              </Button>
            </div>
          </Card>

          <Card className="p-6">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(215,90,45,0.12)] text-ember">
                <Mailbox className="h-5 w-5" />
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Gmail source</p>
                <h3 className="mt-1 text-xl font-semibold">Connect Gmail</h3>
              </div>
            </div>
            <p className="mt-4 text-sm leading-6 text-[#596270]">
              Browser-based Google OAuth creates or reuses a single Gmail source for this workspace. Canvas ICS remains a separate student calendar input.
            </p>
            <div className="mt-5 rounded-[1.25rem] border border-line bg-white/55 p-4 text-sm text-[#314051]">
              <p>Status: {gmailConnected ? "Connected" : "Not connected"}</p>
              <p className="mt-2">Source: {gmailSource ? `#${gmailSource.source_id}` : "Will be created on first connect"}</p>
              <p className="mt-2">Label: INBOX</p>
              {gmailSource?.oauth_account_email ? <p className="mt-2">Account: {gmailSource.oauth_account_email}</p> : null}
            </div>
            <div className="mt-5 flex flex-wrap gap-3">
              <Button className="flex-1" onClick={() => void connectGmail()} disabled={gmailConnecting}>
                {gmailConnecting ? "Redirecting to Google..." : gmailConnected ? "Reconnect Gmail" : "Connect Gmail"}
              </Button>
              {gmailSource ? (
                <Button
                  className="flex-1"
                  variant="ghost"
                  onClick={() => void deleteSource(gmailSource.source_id, gmailSource.provider)}
                  disabled={busyDelete === gmailSource.source_id}
                >
                  {busyDelete === gmailSource.source_id ? "Disconnecting..." : "Disconnect Gmail"}
                </Button>
              ) : null}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
