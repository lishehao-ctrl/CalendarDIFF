import { formatDateTime } from "@/lib/presenters";
import type { IntakePostureView, SourceObservabilityView, SourceRow, SyncStatus, SyncUsageSummary } from "@/lib/types";

const PREVIEW_USAGE = {
  canvasBootstrap: makeUsageSummary({
    successful_call_count: 5,
    usage_record_count: 5,
    latency_ms_total: 4620,
    latency_ms_max: 1180,
    input_tokens: 3480,
    cached_input_tokens: 0,
    cache_creation_input_tokens: 0,
    output_tokens: 510,
    reasoning_tokens: 0,
    total_tokens: 3990,
    api_modes: { responses: 5 },
    models: { "gpt-5.2": 5 },
    task_counts: { calendar_delta_parse: 5 },
  }),
  canvasReplay: makeUsageSummary({
    successful_call_count: 1,
    usage_record_count: 1,
    latency_ms_total: 480,
    latency_ms_max: 480,
    input_tokens: 320,
    cached_input_tokens: 0,
    cache_creation_input_tokens: 0,
    output_tokens: 41,
    reasoning_tokens: 0,
    total_tokens: 361,
    api_modes: { responses: 1 },
    models: { "gpt-5.2": 1 },
    task_counts: { calendar_delta_parse: 1 },
  }),
  gmailBootstrap: makeUsageSummary({
    successful_call_count: 12,
    usage_record_count: 12,
    latency_ms_total: 18600,
    latency_ms_max: 2440,
    input_tokens: 28140,
    cached_input_tokens: 20110,
    cache_creation_input_tokens: 2840,
    output_tokens: 1660,
    reasoning_tokens: 210,
    total_tokens: 30010,
    api_modes: { responses: 12 },
    models: { "gpt-5.2": 12 },
    task_counts: { gmail_bootstrap_parse: 12 },
  }),
  gmailReplay: makeUsageSummary({
    successful_call_count: 3,
    usage_record_count: 3,
    latency_ms_total: 3290,
    latency_ms_max: 1240,
    input_tokens: 4980,
    cached_input_tokens: 3360,
    cache_creation_input_tokens: 0,
    output_tokens: 280,
    reasoning_tokens: 62,
    total_tokens: 5260,
    api_modes: { responses: 3 },
    models: { "gpt-5.2": 3 },
    task_counts: { gmail_replay_parse: 3 },
  }),
};

type BuildOptions = {
  previewMode?: boolean;
  syncStatusesBySource?: Record<number, SyncStatus | undefined>;
};

function sourceKindLabel(source: SourceRow): "calendar" | "email" {
  return source.provider === "ics" ? "calendar" : "email";
}

function formatSourceLabel(source: SourceRow) {
  if (source.provider === "ics") {
    return "Canvas ICS";
  }
  return source.display_name || source.provider || `Source ${source.source_id}`;
}

function makeUsageSummary(summary: Omit<SyncUsageSummary, "cache_hit_ratio" | "avg_latency_ms">): SyncUsageSummary {
  const cacheDenominator = summary.input_tokens + summary.cached_input_tokens + summary.cache_creation_input_tokens;
  return {
    ...summary,
    cache_hit_ratio: cacheDenominator > 0 ? summary.cached_input_tokens / cacheDenominator : null,
    avg_latency_ms: summary.successful_call_count > 0 ? summary.latency_ms_total / summary.successful_call_count : null,
  };
}

function normalizeUsageSummary(raw: unknown): SyncUsageSummary | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const value = raw as Record<string, unknown>;
  const numeric = (key: string) => (typeof value[key] === "number" ? value[key] : 0);
  const successfulCallCount = numeric("successful_call_count");
  const latencyMsTotal = numeric("latency_ms_total");
  const inputTokens = numeric("input_tokens");
  const cachedInputTokens = numeric("cached_input_tokens");
  const cacheCreationInputTokens = numeric("cache_creation_input_tokens");
  const outputTokens = numeric("output_tokens");
  const reasoningTokens = numeric("reasoning_tokens");
  const totalTokens = numeric("total_tokens");
  const cacheDenominator = inputTokens + cachedInputTokens + cacheCreationInputTokens;

  return {
    successful_call_count: successfulCallCount,
    usage_record_count: numeric("usage_record_count"),
    latency_ms_total: latencyMsTotal,
    latency_ms_max: numeric("latency_ms_max"),
    input_tokens: inputTokens,
    cached_input_tokens: cachedInputTokens,
    cache_creation_input_tokens: cacheCreationInputTokens,
    output_tokens: outputTokens,
    reasoning_tokens: reasoningTokens,
    total_tokens: totalTokens,
    cache_hit_ratio: cacheDenominator > 0 ? cachedInputTokens / cacheDenominator : null,
    avg_latency_ms: successfulCallCount > 0 ? latencyMsTotal / successfulCallCount : null,
    api_modes: typeof value.api_modes === "object" && value.api_modes ? (value.api_modes as Record<string, number>) : {},
    models: typeof value.models === "object" && value.models ? (value.models as Record<string, number>) : {},
    task_counts: typeof value.task_counts === "object" && value.task_counts ? (value.task_counts as Record<string, number>) : {},
    last_observed_at: typeof value.last_observed_at === "string" ? value.last_observed_at : null,
  };
}

function previewObservabilityForSource(source: SourceRow): SourceObservabilityView {
  if (source.provider === "ics") {
    return {
      source_id: source.source_id,
      source_label: formatSourceLabel(source),
      source_kind: "calendar",
      runtime_state: source.runtime_state || "active",
      connection_status: "healthy",
      connection_label: "Connected",
      connection_detail: "Calendar feed is active and replay is steady.",
      bootstrap_status: "succeeded",
      replay_status: "succeeded",
      latest_bootstrap_elapsed_ms: 4620,
      latest_replay_elapsed_ms: 480,
      bootstrap_usage: PREVIEW_USAGE.canvasBootstrap,
      replay_usage: PREVIEW_USAGE.canvasReplay,
      latest_sync_label: "Latest replay succeeded",
      latest_sync_detail: "Canvas inventory is in steady-state replay.",
    };
  }

  return {
    source_id: source.source_id,
    source_label: formatSourceLabel(source),
    source_kind: "email",
    runtime_state: source.runtime_state || "active",
    connection_status: "attention",
    connection_label: "Needs reconnect",
    connection_detail: source.last_error_message || "Mailbox auth needs repair before replay is trustworthy.",
    bootstrap_status: "running",
    replay_status: "failed",
    latest_bootstrap_elapsed_ms: 18600,
    latest_replay_elapsed_ms: 3290,
    bootstrap_usage: PREVIEW_USAGE.gmailBootstrap,
    replay_usage: PREVIEW_USAGE.gmailReplay,
    latest_sync_label: "Replay blocked",
    latest_sync_detail: "Reconnect Gmail to restore steady replay parsing.",
  };
}

function inferLatestSync(source: SourceRow, syncStatus: SyncStatus | undefined) {
  if (syncStatus?.progress?.label) {
    return {
      label: syncStatus.progress.label,
      detail: syncStatus.progress.detail || null,
    };
  }
  if (source.last_polled_at) {
    return {
      label: "Last sync completed",
      detail: `Updated ${formatDateTime(source.last_polled_at, "recently")}`,
    };
  }
  return {
    label: "No completed sync yet",
    detail: null,
  };
}

function inferLiveObservability(source: SourceRow, syncStatus: SyncStatus | undefined): SourceObservabilityView {
  const usage = normalizeUsageSummary(syncStatus?.metadata && typeof syncStatus.metadata === "object" ? (syncStatus.metadata as Record<string, unknown>).llm_usage_summary : null);
  const needsAttention = Boolean(source.last_error_message) || source.runtime_state === "rebind_pending" || source.config_state === "rebind_pending";
  const latestSync = inferLatestSync(source, syncStatus);
  const bootstrapRunning = source.runtime_state === "rebind_pending" || source.config_state === "rebind_pending" || !source.last_polled_at;

  return {
    source_id: source.source_id,
    source_label: formatSourceLabel(source),
    source_kind: sourceKindLabel(source),
    runtime_state: source.runtime_state || "unknown",
    connection_status: !source.is_active ? "disconnected" : needsAttention ? "attention" : "healthy",
    connection_label: !source.is_active ? "Disconnected" : needsAttention ? "Attention needed" : "Connected",
    connection_detail:
      source.last_error_message ||
      (!source.is_active ? "Reconnect this source before trusting intake." : source.provider === "ics" ? "Calendar feed is connected." : "Mailbox is connected."),
    bootstrap_status: bootstrapRunning ? (needsAttention ? "running" : "unknown") : "succeeded",
    replay_status: needsAttention ? "failed" : source.is_active ? "succeeded" : "idle",
    latest_bootstrap_elapsed_ms: bootstrapRunning ? usage?.latency_ms_total || null : usage?.latency_ms_total || null,
    latest_replay_elapsed_ms: !bootstrapRunning ? usage?.latency_ms_total || null : null,
    bootstrap_usage: bootstrapRunning ? usage : null,
    replay_usage: !bootstrapRunning ? usage : null,
    latest_sync_label: latestSync.label,
    latest_sync_detail: latestSync.detail,
  };
}

export function buildSourceObservabilityViews(sources: SourceRow[], options?: BuildOptions): SourceObservabilityView[] {
  const syncStatusesBySource = options?.syncStatusesBySource || {};
  return sources.map((source) =>
    options?.previewMode
      ? previewObservabilityForSource(source)
      : inferLiveObservability(source, syncStatusesBySource[source.source_id]),
  );
}

function usageState(summary: SyncUsageSummary | null): "normal" | "elevated" | "unknown" {
  if (!summary) return "unknown";
  return summary.total_tokens >= 10000 || (summary.avg_latency_ms || 0) >= 2000 ? "elevated" : "normal";
}

export function buildIntakePosture(observability: SourceObservabilityView[]): IntakePostureView {
  const warmingSourceCount = observability.filter((source) => source.bootstrap_status === "running").length;
  const replayAttentionCount = observability.filter((source) => source.replay_status === "failed" || source.replay_status === "running").length;
  const bootstrapState = observability.some((source) => usageState(source.bootstrap_usage) === "elevated")
    ? "elevated"
    : observability.some((source) => usageState(source.bootstrap_usage) === "normal")
      ? "normal"
      : "unknown";
  const replayState = observability.some((source) => usageState(source.replay_usage) === "elevated")
    ? "elevated"
    : observability.some((source) => usageState(source.replay_usage) === "normal")
      ? "normal"
      : "unknown";

  return {
    warming_source_count: warmingSourceCount,
    replay_health: replayAttentionCount > 0 ? "attention" : observability.length > 0 ? "healthy" : "unknown",
    bootstrap_cost_state: bootstrapState,
    replay_cost_state: replayState,
    warming_label: warmingSourceCount > 0 ? `${warmingSourceCount} source${warmingSourceCount === 1 ? "" : "s"} warming up` : "No source warmup",
    replay_label: replayAttentionCount > 0 ? "Replay needs attention" : "Replay looks healthy",
    cost_label:
      bootstrapState === "elevated"
        ? "Bootstrap cost is elevated"
        : replayState === "elevated"
          ? "Replay cost is elevated"
          : "Cost looks normal",
  };
}

export function formatElapsedMs(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "Unavailable";
  if (value < 1000) return `${Math.round(value)} ms`;
  if (value < 60000) return `${(value / 1000).toFixed(1)} s`;
  return `${(value / 60000).toFixed(1)} min`;
}

export function formatUsageSummary(summary: SyncUsageSummary | null) {
  if (!summary) {
    return {
      headline: "Unavailable",
      detail: "No live sample yet",
    };
  }
  const cacheHit = summary.cache_hit_ratio === null ? "No cache" : `${Math.round(summary.cache_hit_ratio * 100)}% cache`;
  const latency = summary.avg_latency_ms === null ? "No latency sample" : `${Math.round(summary.avg_latency_ms)} ms avg`;
  return {
    headline: `${summary.total_tokens.toLocaleString()} tokens`,
    detail: `${cacheHit} · ${latency}`,
  };
}
