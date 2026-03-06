"use client";

import { useMemo, useState } from "react";
import { CalendarSync, Mailbox, RefreshCw, ShieldAlert, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { backendFetch } from "@/lib/backend";
import { formatDateTime, formatStatusLabel } from "@/lib/presenters";
import type { SourceRow, SyncStatus } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

const blankForm = {
  source_key: "",
  display_name: "",
  secrets_url: ""
};

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

export function SourcesPanel() {
  const { data, loading, error, refresh } = useResource<SourceRow[]>("/sources");
  const [form, setForm] = useState(blankForm);
  const [syncState, setSyncState] = useState<Record<number, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [busyDelete, setBusyDelete] = useState<number | null>(null);
  const [banner, setBanner] = useState<Banner>(null);

  const sources = useMemo(() => data || [], [data]);
  const activeCount = sources.filter((source) => source.is_active).length;
  const erroredCount = sources.filter((source) => Boolean(source.last_error_message)).length;

  async function createIcsSource() {
    setSubmitting(true);
    setBanner(null);
    try {
      await backendFetch<SourceRow>("/sources", {
        method: "POST",
        body: JSON.stringify({
          source_kind: "calendar",
          provider: "ics",
          source_key: form.source_key,
          display_name: form.display_name,
          config: {},
          secrets: { url: form.secrets_url }
        })
      });
      setForm(blankForm);
      setBanner({ tone: "info", text: "ICS source created. You can trigger a manual sync immediately." });
      await refresh();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to create source" });
    } finally {
      setSubmitting(false);
    }
  }

  async function deleteSource(sourceId: number) {
    const confirmed = window.confirm("Delete this source from the workspace?");
    if (!confirmed) {
      return;
    }

    setBusyDelete(sourceId);
    setBanner(null);
    try {
      await backendFetch(`/sources/${sourceId}`, { method: "DELETE" });
      setBanner({ tone: "info", text: `Source #${sourceId} deleted.` });
      await refresh();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to delete source" });
    } finally {
      setBusyDelete(null);
    }
  }

  async function triggerSync(sourceId: number) {
    setSyncState((prev) => ({ ...prev, [sourceId]: "queued" }));
    setBanner(null);
    try {
      const created = await backendFetch<{ request_id: string }>(`/sources/${sourceId}/sync-requests`, {
        method: "POST",
        body: JSON.stringify({ metadata: { kind: "ui_manual_sync" } })
      });
      for (let attempt = 0; attempt < 15; attempt += 1) {
        const status = await backendFetch<SyncStatus>(`/sync-requests/${created.request_id}`);
        const normalized = status.status.toLowerCase();
        setSyncState((prev) => ({ ...prev, [sourceId]: normalized }));
        if (status.status === "SUCCEEDED" || status.status === "FAILED") {
          if (status.status === "SUCCEEDED") {
            setBanner({ tone: "info", text: `Source #${sourceId} sync succeeded.` });
          }
          if (status.status === "FAILED") {
            setBanner({ tone: "error", text: status.error_message || status.connector_result?.error_message || `Source #${sourceId} sync failed.` });
          }
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      await refresh();
    } catch (err) {
      const text = err instanceof Error ? err.message : "Sync failed";
      setSyncState((prev) => ({ ...prev, [sourceId]: "failed" }));
      setBanner({ tone: "error", text });
    }
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
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Active feeds</p>
          <p className="mt-3 text-3xl font-semibold">{activeCount}</p>
          <p className="mt-2 text-sm text-[#596270]">Feeds that can accept manual or worker-driven sync requests.</p>
        </Card>
        <Card className="p-5">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Errored sources</p>
          <p className="mt-3 text-3xl font-semibold">{erroredCount}</p>
          <p className="mt-2 text-sm text-[#596270]">Sources with a recorded connector or validation failure.</p>
        </Card>
        <Card className="p-5">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Auth-gated Gmail</p>
          <p className="mt-3 text-3xl font-semibold">1</p>
          <p className="mt-2 text-sm text-[#596270]">Visible in the UI, intentionally disabled until backend auth hardening is complete.</p>
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
                ICS sources are fully actionable. Use manual sync to force fresh evidence into review without waiting for the worker cadence.
              </p>
            </div>
            <Badge tone="approved">API-backed</Badge>
          </div>

          <div className="mt-5 space-y-4">
            {sources.length === 0 ? (
              <EmptyState title="No sources yet" description="Create an ICS source on the right to open the intake loop." />
            ) : (
              sources.map((source) => {
                const syncLabel = syncState[source.source_id];
                return (
                  <Card key={source.source_id} className="overflow-hidden p-5">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div className="space-y-3">
                        <div className="flex flex-wrap items-center gap-3">
                          <h4 className="text-lg font-semibold">{source.display_name}</h4>
                          <Badge tone={source.is_active ? "active" : "default"}>{source.provider}</Badge>
                          <Badge tone={syncTone(syncLabel)}>{formatStatusLabel(syncLabel, "Idle")}</Badge>
                        </div>
                        <p className="text-sm text-[#596270]">{source.source_kind} source · key `{source.source_key}`</p>
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
                          onClick={() => void deleteSource(source.source_id)}
                          disabled={busyDelete === source.source_id}
                        >
                          <Trash2 className="mr-2 h-4 w-4" />
                          {busyDelete === source.source_id ? "Removing..." : "Delete"}
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
                <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Create source</p>
                <h3 className="mt-1 text-xl font-semibold">Add an ICS feed</h3>
              </div>
            </div>
            <div className="mt-5 space-y-4">
              <div>
                <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="source-key">
                  Source key
                </label>
                <Input id="source-key" placeholder="winter-quarter-cse151a" value={form.source_key} onChange={(event) => setForm((prev) => ({ ...prev, source_key: event.target.value }))} />
              </div>
              <div>
                <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="display-name">
                  Display name
                </label>
                <Input id="display-name" placeholder="CSE 151A Winter quarter ICS" value={form.display_name} onChange={(event) => setForm((prev) => ({ ...prev, display_name: event.target.value }))} />
              </div>
              <div>
                <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="ics-url">
                  ICS URL
                </label>
                <Input id="ics-url" placeholder="https://example.com/calendar.ics" value={form.secrets_url} onChange={(event) => setForm((prev) => ({ ...prev, secrets_url: event.target.value }))} />
              </div>
              <Button className="w-full" disabled={submitting || !form.source_key || !form.display_name || !form.secrets_url} onClick={() => void createIcsSource()}>
                {submitting ? "Adding source..." : "Create ICS source"}
              </Button>
            </div>
          </Card>

          <Card className="p-6">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(215,90,45,0.12)] text-ember">
                <Mailbox className="h-5 w-5" />
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Reserved entry</p>
                <h3 className="mt-1 text-xl font-semibold">Gmail connect</h3>
              </div>
            </div>
            <p className="mt-4 text-sm leading-6 text-[#596270]">
              The UI keeps Gmail visible as a first-class source family, but the actual OAuth connect path is intentionally held back until backend callback hardening is complete.
            </p>
            <div className="mt-5 rounded-[1.25rem] border border-dashed border-line bg-white/50 p-4 text-sm text-[#314051]">
              <div className="flex items-start gap-3">
                <ShieldAlert className="mt-0.5 h-4 w-4 text-ember" />
                <p>Gmail connect pending backend auth finalization.</p>
              </div>
            </div>
            <Button className="mt-4 w-full" variant="secondary" disabled>
              Gmail connect pending backend auth finalization
            </Button>
          </Card>
        </div>
      </div>
    </div>
  );
}
