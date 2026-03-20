"use client";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { formatElapsedMs, formatUsageSummary } from "@/lib/source-observability";
import { formatStatusLabel } from "@/lib/presenters";
import type { SourceObservabilityView } from "@/lib/types";

function observabilityTone(status: SourceObservabilityView["bootstrap_status"] | SourceObservabilityView["replay_status"]) {
  if (status === "failed") return "error";
  if (status === "running") return "pending";
  if (status === "succeeded") return "approved";
  return "info";
}

function MetricBlock({
  label,
  tone,
  headline,
  detail,
}: {
  label: string;
  tone?: string;
  headline: string;
  detail: string;
}) {
  return (
    <div className="rounded-[1rem] border border-line/80 bg-white/72 p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{label}</p>
        {tone ? <Badge tone={tone}>{formatStatusLabel(tone === "approved" ? "ok" : tone)}</Badge> : null}
      </div>
      <p className="mt-2 text-sm font-medium text-ink">{headline}</p>
      <p className="mt-1 text-xs leading-5 text-[#596270]">{detail}</p>
    </div>
  );
}

export function SourceObservabilitySections({
  observability,
  className,
}: {
  observability: SourceObservabilityView;
  className?: string;
}) {
  const bootstrapUsage = formatUsageSummary(observability.bootstrap_usage);
  const replayUsage = formatUsageSummary(observability.replay_usage);
  const latestSyncHeadline = observability.latest_sync_label || "No live sync";
  const latestSyncDetail = observability.latest_sync_detail || "Run a sync to sample intake posture.";

  return (
    <div className={cn("grid gap-3 sm:grid-cols-2", className)}>
      <MetricBlock
        label="Connection"
        tone={observability.connection_status === "healthy" ? "approved" : observability.connection_status === "attention" ? "pending" : "info"}
        headline={observability.connection_label}
        detail={observability.connection_detail}
      />
      <MetricBlock
        label="Bootstrap"
        tone={observabilityTone(observability.bootstrap_status)}
        headline={formatStatusLabel(observability.bootstrap_status)}
        detail={formatElapsedMs(observability.latest_bootstrap_elapsed_ms)}
      />
      <MetricBlock
        label="Replay"
        tone={observabilityTone(observability.replay_status)}
        headline={formatStatusLabel(observability.replay_status)}
        detail={formatElapsedMs(observability.latest_replay_elapsed_ms)}
      />
      <MetricBlock label="Latest sync" headline={latestSyncHeadline} detail={latestSyncDetail} />
      <MetricBlock
        label="LLM cost"
        headline={replayUsage.headline === "Unavailable" ? bootstrapUsage.headline : replayUsage.headline}
        detail={replayUsage.headline === "Unavailable" ? bootstrapUsage.detail : replayUsage.detail}
      />
    </div>
  );
}
