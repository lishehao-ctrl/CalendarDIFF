"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Mailbox, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { SourceSyncProgress } from "@/components/source-sync-progress";
import { startOnboardingGmailOAuth } from "@/lib/api/onboarding";
import { createOAuthSession, deleteSource, listSources } from "@/lib/api/sources";
import { useApiResource } from "@/lib/use-api-resource";
import type { SourceRow } from "@/lib/types";

export function GmailSourceSetupPanel() {
  const { data, loading, error, refresh } = useApiResource<SourceRow[]>(() => listSources({ status: "all" }), []);
  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const source = useMemo(() => (data || []).find((row) => row.provider === "gmail") || null, [data]);

  useEffect(() => {
    if (!source || (source.runtime_state !== "running" && source.runtime_state !== "queued" && source.runtime_state !== "rebind_pending" && !source.sync_progress)) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void refresh();
    }, 2000);
    return () => window.clearInterval(intervalId);
  }, [refresh, source]);

  async function connect() {
    setConnecting(true);
    setBanner(null);
    try {
      const session = source
        ? await createOAuthSession(source.source_id, { provider: "gmail" })
        : await startOnboardingGmailOAuth({ label_id: "INBOX", return_to: "sources" });
      window.location.assign(session.authorization_url);
    } catch (err) {
      setConnecting(false);
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to start Gmail OAuth" });
    }
  }

  async function archive() {
    if (!source) return;
    const confirmed = window.confirm("Disconnect this Gmail mailbox and move it to Archived Sources?");
    if (!confirmed) return;
    setDisconnecting(true);
    setBanner(null);
    try {
      await deleteSource(source.source_id);
      setBanner({ tone: "info", text: "Mailbox disconnected and archived." });
      await refresh();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to disconnect Gmail" });
    } finally {
      setDisconnecting(false);
    }
  }

  if (loading) return <LoadingState label="gmail setup" />;
  if (error) return <ErrorState message={error} />;
  if (!data) return <EmptyState title="Source state unavailable" description="Unable to load the current Gmail configuration." />;

  return (
    <div className="space-y-5">
      <Card className="p-6 md:p-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Gmail setup</p>
            <h3 className="mt-3 text-2xl font-semibold">Manage your Gmail mailbox</h3>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-[#596270]">Connect, reconnect, or disconnect the single Gmail mailbox used by this workspace.</p>
          </div>
          <Button asChild size="sm" variant="ghost">
            <Link href="/sources">
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

        <div className="mt-6 grid gap-5 xl:grid-cols-[1fr_0.95fr]">
          <Card className="bg-white/60 p-5">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(215,90,45,0.12)] text-ember">
                <Mailbox className="h-5 w-5" />
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Current mailbox</p>
                <h4 className="mt-2 text-lg font-semibold text-ink">{source ? "Gmail configured" : "No Gmail mailbox yet"}</h4>
              </div>
            </div>
            <div className="mt-5 rounded-[1.15rem] border border-line/80 bg-white/70 p-4 text-sm text-[#314051]">
              <p>Status: {source ? (source.is_active ? "Connected" : "Archived") : "Not connected"}</p>
              <p className="mt-2">Source: {source ? `#${source.source_id}` : "Will be created on first connect"}</p>
              <p className="mt-2">Label: INBOX</p>
              {source?.oauth_account_email ? <p className="mt-2">Account: {source.oauth_account_email}</p> : null}
            </div>
            <SourceSyncProgress className="mt-4" progress={source?.sync_progress} />
            {source ? (
              <div className="mt-5 flex flex-wrap gap-3">
                <Button variant="ghost" onClick={() => void archive()} disabled={disconnecting}>
                  <Trash2 className="mr-2 h-4 w-4" />
                  {disconnecting ? "Disconnecting..." : "Disconnect mailbox"}
                </Button>
              </div>
            ) : null}
          </Card>
          <Card className="bg-white/60 p-5">
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Connection flow</p>
            <h4 className="mt-3 text-lg font-semibold text-ink">Use browser-based Google OAuth</h4>
            <p className="mt-2 text-sm leading-6 text-[#596270]">Start the OAuth flow to connect or reconnect the single Gmail mailbox for this workspace.</p>
            <div className="mt-5 flex flex-wrap gap-3">
              <Button onClick={() => void connect()} disabled={connecting}>
                {connecting ? "Redirecting to Google..." : source && source.is_active ? "Reconnect Gmail" : "Connect Gmail"}
              </Button>
            </div>
          </Card>
        </div>
      </Card>
    </div>
  );
}
