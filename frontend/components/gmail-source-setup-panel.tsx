"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Mailbox, Trash2 } from "lucide-react";
import { SourceRecoveryAgentCard } from "@/components/source-recovery-agent-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/data-states";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";
import { WorkbenchLoadingShell } from "@/components/workbench-loading-shell";
import { SourceSyncProgress } from "@/components/source-sync-progress";
import { withBasePath } from "@/lib/demo-mode";
import { startOnboardingGmailOAuth } from "@/lib/api/onboarding";
import { translate } from "@/lib/i18n/runtime";
import { buildSourceObservabilityViews } from "@/lib/source-observability";
import { invalidateSourceCaches } from "@/lib/source-cache";
import { createOAuthSession, deleteSource, getSyncRequest, listSources, sourceListCacheKey } from "@/lib/api/sources";
import { useApiResource } from "@/lib/use-api-resource";
import { workbenchPanelClassName, workbenchStateSurfaceClassName, workbenchSupportPanelClassName } from "@/lib/workbench-styles";
import type { SourceRow, SyncStatus } from "@/lib/types";

const DeferredSourceObservabilitySections = dynamic(
  () => import("@/components/source-observability-sections").then((mod) => mod.SourceObservabilitySections),
  {
    loading: () => <PanelLoadingPlaceholder rows={2} className="mt-4 p-4" />,
  },
);

export function GmailSourceSetupPanel({ basePath = "" }: { basePath?: string }) {
  const { data, loading, error, refresh } = useApiResource<SourceRow[]>(() => listSources({ status: "all" }), [], null, {
    cacheKey: sourceListCacheKey("all"),
  });
  const [syncDetail, setSyncDetail] = useState<SyncStatus | null>(null);
  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const source = useMemo(() => (data || []).find((row) => row.provider === "gmail") || null, [data]);

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
  const needsReconnect = Boolean(
    source &&
      source.is_active &&
      (source.oauth_connection_status === "not_connected" || source.source_recovery?.next_action === "reconnect_gmail"),
  );
  const connectionBadgeTone = !source ? "info" : !source.is_active ? "info" : needsReconnect ? "error" : "approved";
  const connectionBadgeLabel = !source ? translate("sourceConnect.gmailPanel.notConnected") : !source.is_active ? translate("sourceConnect.gmailPanel.archived") : needsReconnect ? translate("sourceConnect.gmailPanel.reconnectRequired") : translate("sourceConnect.gmailPanel.connected");
  const currentMailboxStatus = !source ? translate("sourceConnect.gmailPanel.notConnected") : !source.is_active ? translate("sourceConnect.gmailPanel.archived") : needsReconnect ? translate("sourceConnect.gmailPanel.reconnectRequired") : translate("sourceConnect.gmailPanel.connected");
  const connectionSummary = !source
    ? translate("sourceConnect.gmailPanel.noMailbox")
    : !source.is_active
      ? translate("sourceConnect.gmailPanel.archivedSummary")
      : needsReconnect
        ? translate("sourceConnect.gmailPanel.reconnectSummary")
        : translate("sourceConnect.gmailPanel.connectedSummary");

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
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("sourceConnect.gmailPanel.oauthFailed") });
    }
  }

  async function archive() {
    if (!source) return;
    const confirmed = window.confirm(translate("sourceConnect.gmailPanel.archiveConfirm"));
    if (!confirmed) return;
    setDisconnecting(true);
    setBanner(null);
    try {
      await deleteSource(source.source_id);
      invalidateSourceCaches(source.source_id);
      setBanner({ tone: "info", text: translate("sourceConnect.gmailPanel.disconnectSuccess") });
      await refresh({ force: true });
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("sourceConnect.gmailPanel.disconnectFailed") });
    } finally {
      setDisconnecting(false);
    }
  }

  if (loading) return <WorkbenchLoadingShell variant="source-connect" />;
  if (error) return <ErrorState message={error} />;
  if (!data) return <EmptyState title={translate("sourceConnect.gmailPanel.stateUnavailableTitle")} description={translate("sourceConnect.gmailPanel.stateUnavailableDescription")} />;

  return (
    <div className="space-y-5">
      <Card className="p-6 md:p-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">{translate("sourceConnect.gmailPanel.setupEyebrow")}</p>
            <h3 className="mt-3 text-2xl font-semibold">{translate("sourceConnect.gmailPanel.title")}</h3>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-[#596270]">{translate("sourceConnect.gmailPanel.summary")}</p>
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
              <Badge tone={connectionBadgeTone}>{connectionBadgeLabel}</Badge>
            </div>
            <DeferredSourceObservabilitySections observability={observability} className="mt-4" />
          </Card>
        ) : null}

        <div className="mt-6 grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="space-y-5">
          <Card className={workbenchPanelClassName("secondary", "p-5")}>
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(215,90,45,0.12)] text-ember">
                <Mailbox className="h-5 w-5" />
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sourceConnect.gmailPanel.currentMailbox")}</p>
                <h4 className="mt-2 text-lg font-semibold text-ink">{source ? translate("sourceConnect.gmailPanel.configured") : translate("sourceConnect.gmailPanel.missing")}</h4>
              </div>
            </div>
            <div className={workbenchSupportPanelClassName("default", "mt-5 p-4 text-sm text-[#314051]")}>
              <p>{translate("sourceConnect.gmailPanel.status")}: {currentMailboxStatus}</p>
              <p className="mt-2">{translate("sourceConnect.gmailPanel.source")}: {source ? `#${source.source_id}` : translate("sourceConnect.gmailPanel.sourceWillBeCreated")}</p>
              <p className="mt-2">{translate("sourceConnect.gmailPanel.label")}: INBOX</p>
              {source?.oauth_account_email ? <p className="mt-2">{translate("sourceConnect.gmailPanel.account")}: {source.oauth_account_email}</p> : null}
            </div>
            <SourceSyncProgress className="mt-4" progress={source?.sync_progress} stableLabel="Syncing Gmail source" />
            <p className="mt-4 text-sm leading-6 text-[#596270]">{connectionSummary}</p>
            {source ? (
              <div className="mt-5 flex flex-wrap gap-3">
                <Button variant="ghost" onClick={() => void archive()} disabled={disconnecting}>
                  <Trash2 className="mr-2 h-4 w-4" />
                  {disconnecting ? translate("sourceConnect.gmailPanel.disconnecting") : translate("sourceConnect.gmailPanel.disconnectMailbox")}
                </Button>
              </div>
            ) : null}
          </Card>
          <Card className={workbenchPanelClassName("secondary", "p-5")}>
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sourceConnect.gmailPanel.connectionFlow")}</p>
            <h4 className="mt-3 text-lg font-semibold text-ink">{translate("sourceConnect.gmailPanel.connectionFlowTitle")}</h4>
            <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("sourceConnect.gmailPanel.connectionFlowSummary")}</p>
            <div className="mt-5 flex flex-wrap gap-3">
              <Button onClick={() => void connect()} disabled={connecting}>
                {connecting ? translate("sourceConnect.gmailPanel.redirecting") : source && source.is_active ? translate("sourceConnect.gmailPanel.reconnect") : translate("sourceConnect.gmailPanel.connect")}
              </Button>
            </div>
          </Card>
          </div>
          <div className="space-y-4">
            {source ? <SourceRecoveryAgentCard sourceId={source.source_id} basePath={basePath} /> : null}
          </div>
        </div>
      </Card>
    </div>
  );
}
