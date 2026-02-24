import { ChangeFeedRecord, ChangeSummary, ChangeSummarySide } from "@/lib/types";

const TIME_FIELD_PRIORITY = ["start_at_utc", "internal_date", "due_at", "end_at_utc"] as const;
const FALLBACK_TIMEZONE = "UTC";

let cachedViewerTimeZone: string | null = null;

export function deriveChangeSummary(change: ChangeFeedRecord): ChangeSummary {
  const sourceType = normalizeSourceType(change.input_type);
  const sourceLabelFallback = sourceType === "email" ? "Email input" : sourceType === "ics" ? "Calendar input" : null;

  const beforePayload = asRecord(change.before_json);
  const afterPayload = asRecord(change.after_json);
  const legacyOldObservedAt = extractObservedAt(change.before_raw_evidence_key);
  const legacyNewObservedAt = extractObservedAt(change.after_raw_evidence_key);

  const candidate = asRecord(change.change_summary);
  return {
    old: normalizeSummarySide(asRecord(candidate?.old), {
      sourceType,
      sourceLabel: sourceLabelFallback,
      fallbackPayload: beforePayload,
      fallbackObservedAt: legacyOldObservedAt,
    }),
    new: normalizeSummarySide(asRecord(candidate?.new), {
      sourceType,
      sourceLabel: sourceLabelFallback,
      fallbackPayload: afterPayload,
      fallbackObservedAt: legacyNewObservedAt,
    }),
  };
}

export function formatSummaryDate(value: string | null): string {
  if (!value) {
    return "n/a";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "n/a";
  }
  const timeZone = resolveViewerTimeZone();
  return new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(parsed);
}

function resolveViewerTimeZone(): string {
  if (cachedViewerTimeZone !== null) {
    return cachedViewerTimeZone;
  }
  const candidate = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (isValidTimeZone(candidate)) {
    cachedViewerTimeZone = candidate;
    return candidate;
  }
  cachedViewerTimeZone = FALLBACK_TIMEZONE;
  return FALLBACK_TIMEZONE;
}

function isValidTimeZone(value: unknown): value is string {
  if (typeof value !== "string" || value.trim() === "") {
    return false;
  }
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: value });
    return true;
  } catch {
    return false;
  }
}

function normalizeSummarySide(
  side: Record<string, unknown> | null,
  fallback: {
    sourceType: "ics" | "email" | null;
    sourceLabel: string | null;
    fallbackPayload: Record<string, unknown> | null;
    fallbackObservedAt: string | null;
  }
): ChangeSummarySide {
  return {
    value_time: normalizeIsoString(readString(side?.value_time)) ?? extractValueTime(fallback.fallbackPayload),
    source_label: readString(side?.source_label) ?? fallback.sourceLabel,
    source_type: normalizeSourceType(side?.source_type) ?? fallback.sourceType,
    source_observed_at: normalizeIsoString(readString(side?.source_observed_at)) ?? fallback.fallbackObservedAt,
  };
}

function extractValueTime(payload: Record<string, unknown> | null): string | null {
  if (!payload) {
    return null;
  }
  for (const key of TIME_FIELD_PRIORITY) {
    const value = normalizeIsoString(readString(payload[key]));
    if (value) {
      return value;
    }
  }
  return null;
}

function extractObservedAt(rawEvidenceKey: Record<string, unknown> | null): string | null {
  if (!rawEvidenceKey) {
    return null;
  }
  return normalizeIsoString(readString(rawEvidenceKey.retrieved_at));
}

function normalizeSourceType(value: unknown): "ics" | "email" | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim().toLowerCase();
  if (normalized === "ics" || normalized === "email") {
    return normalized;
  }
  return null;
}

function normalizeIsoString(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed.toISOString();
}

function readString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed || null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}
