import type {
  ChangesWorkbenchSummary,
  SourceObservabilityResponse,
  SourceObservabilitySync,
  SourceRow,
} from "@/lib/types";

export type SourceImportPhase = "baseline_running" | "initial_review_ready" | "replay_review" | "unknown";

export type SourceImportState = {
  sourceId: number;
  source: SourceRow;
  phase: SourceImportPhase;
  title: string;
  summary: string;
  bootstrapRecordsCount: number | null;
  bootstrapStatus: SourceObservabilitySync["status"] | null;
  latestReplayExists: boolean;
  importedCount: number;
  reviewRequiredCount: number;
  ignoredCount: number;
  conflictCount: number;
};

function getRecordsCount(sync: SourceObservabilitySync | null | undefined) {
  const value = sync?.connector_result;
  if (!value || typeof value !== "object") {
    return null;
  }
  const raw = (value as Record<string, unknown>).records_count;
  return typeof raw === "number" ? raw : null;
}

export function deriveSourceImportState(source: SourceRow, observability: SourceObservabilityResponse | null | undefined): SourceImportState {
  const bootstrap = observability?.bootstrap || null;
  const bootstrapSummary = observability?.bootstrap_summary || null;
  const latestReplay = observability?.latest_replay || null;
  const active = observability?.active || null;
  const bootstrapRecordsCount = getRecordsCount(bootstrap);
  const latestReplayExists = latestReplay !== null;
  const importedCount = bootstrapSummary?.imported_count || 0;
  const reviewRequiredCount = bootstrapSummary?.review_required_count || 0;
  const ignoredCount = bootstrapSummary?.ignored_count || 0;
  const conflictCount = bootstrapSummary?.conflict_count || 0;
  const bootstrapState = bootstrapSummary?.state || null;
  const bootstrapInFlight =
    bootstrapState === "running" ||
    (active?.phase === "bootstrap" && ["PENDING", "QUEUED", "RUNNING"].includes(active.status)) ||
    (bootstrap !== null && ["PENDING", "QUEUED", "RUNNING"].includes(bootstrap.status));

  if (bootstrapInFlight) {
    return {
      sourceId: source.source_id,
      source,
      phase: "baseline_running",
      title: "Building first baseline",
      summary: "The first import is still running.",
      bootstrapRecordsCount,
      bootstrapStatus: active?.phase === "bootstrap" ? active.status : bootstrap?.status || null,
      latestReplayExists,
      importedCount,
      reviewRequiredCount,
      ignoredCount,
      conflictCount,
    };
  }

  if (bootstrapState === "review_required" || reviewRequiredCount > 0) {
    return {
      sourceId: source.source_id,
      source,
      phase: "initial_review_ready",
      title: "Initial Review is next",
      summary:
        reviewRequiredCount === 1
          ? "The first import finished with 1 baseline item that still needs review."
          : `The first import finished with ${reviewRequiredCount} baseline items that still need review.`,
      bootstrapRecordsCount,
      bootstrapStatus: bootstrap?.status || null,
      latestReplayExists,
      importedCount,
      reviewRequiredCount,
      ignoredCount,
      conflictCount,
    };
  }

  if (bootstrapState === "completed" || latestReplayExists || bootstrap?.status === "SUCCEEDED") {
    return {
      sourceId: source.source_id,
      source,
      phase: "replay_review",
      title: "Replay review",
      summary: "This source is already in its normal ongoing change cycle.",
      bootstrapRecordsCount,
      bootstrapStatus: bootstrap?.status || null,
      latestReplayExists,
      importedCount,
      reviewRequiredCount,
      ignoredCount,
      conflictCount,
    };
  }

  return {
    sourceId: source.source_id,
    source,
    phase: "unknown",
    title: "Phase not exposed",
    summary: "This source does not yet expose enough phase information for frontend separation.",
    bootstrapRecordsCount,
    bootstrapStatus: bootstrap?.status || null,
    latestReplayExists,
    importedCount,
    reviewRequiredCount,
    ignoredCount,
    conflictCount,
  };
}

export type InitialReviewSummary = {
  readyCount: number;
  runningCount: number;
  candidates: SourceImportState[];
  primaryCtaHref: string;
  primaryCtaLabel: string;
  summaryTitle: string;
  summaryBody: string;
};

export function buildInitialReviewSummary(params: {
  sources: SourceRow[];
  observabilityMap: Record<number, SourceObservabilityResponse | undefined>;
  workbenchSummary: ChangesWorkbenchSummary;
}): InitialReviewSummary {
  const { sources, observabilityMap, workbenchSummary } = params;
  const candidates = sources
    .filter((source) => source.is_active)
    .map((source) => deriveSourceImportState(source, observabilityMap[source.source_id]))
    .filter((state) => state.phase === "baseline_running" || state.phase === "initial_review_ready");

  const readyCount = candidates.filter((state) => state.phase === "initial_review_ready").length;
  const runningCount = candidates.filter((state) => state.phase === "baseline_running").length;

  if (readyCount > 0) {
    return {
      readyCount,
      runningCount,
      candidates,
      primaryCtaHref: "/initial-review",
      primaryCtaLabel: "Open Initial Review",
      summaryTitle: "Initial Review",
      summaryBody:
        readyCount === 1
          ? "A source finished its first baseline import. Review the initial import before treating later changes as daily replay."
          : `${readyCount} sources finished their first baseline import. Review the initial import before treating later changes as daily replay.`,
    };
  }

  if (runningCount > 0) {
    return {
      readyCount,
      runningCount,
      candidates,
      primaryCtaHref: "/sources",
      primaryCtaLabel: "Open Sources",
      summaryTitle: "Baseline import",
      summaryBody:
        runningCount === 1
          ? "A source is still building its first baseline."
          : `${runningCount} sources are still building their first baseline.`,
    };
  }

  return {
    readyCount: 0,
    runningCount: 0,
    candidates: [],
    primaryCtaHref:
      workbenchSummary.recommended_lane === "sources"
        ? "/sources"
        : workbenchSummary.recommended_lane === "families"
          ? "/families"
          : workbenchSummary.recommended_lane === "initial_review"
            ? "/initial-review"
            : "/changes",
    primaryCtaLabel:
      workbenchSummary.recommended_lane === "sources"
        ? "Open Sources"
        : workbenchSummary.recommended_lane === "families"
          ? "Open Families"
          : workbenchSummary.recommended_lane === "initial_review"
            ? "Open Initial Review"
            : "Open Changes",
    summaryTitle: "Replay Review",
    summaryBody: "Use Changes for ongoing review after the baseline is established.",
  };
}
