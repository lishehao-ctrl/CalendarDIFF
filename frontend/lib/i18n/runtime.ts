import { en } from "@/lib/i18n/dictionaries/en";
import { zhCN } from "@/lib/i18n/dictionaries/zh-CN";
import { intlLocale, type Locale } from "@/lib/i18n/locales";

export const dictionaries = {
  en,
  "zh-CN": zhCN,
} as const;

export type Dictionary = (typeof dictionaries)[Locale];

let runtimeLocale: Locale = "en";

type Primitive = string | number | boolean | null | undefined;

function getByPath(target: unknown, path: string) {
  return path.split(".").reduce<unknown>((current, segment) => {
    if (!current || typeof current !== "object") {
      return undefined;
    }
    return (current as Record<string, unknown>)[segment];
  }, target);
}

function interpolate(text: string, vars?: Record<string, Primitive>) {
  if (!vars) {
    return text;
  }
  return text.replace(/\{(\w+)\}/g, (_, key) => {
    const value = vars[key];
    return value === null || value === undefined ? "" : String(value);
  });
}

const STATUS_KEYS: Record<string, string> = {
  pending: "common.status.pending",
  approved: "common.status.approved",
  rejected: "common.status.rejected",
  all: "common.status.all",
  succeeded: "common.status.succeeded",
  failed: "common.status.failed",
  changed: "common.status.changed",
  active: "common.status.active",
  inactive: "common.status.inactive",
  archived: "common.status.archived",
  queued: "common.status.queued",
  running: "common.status.running",
  connected: "common.status.connected",
  disconnected: "common.status.disconnected",
  healthy: "common.status.healthy",
  attention: "common.status.attention",
  blocked: "common.status.blocked",
  low: "common.status.low",
  medium: "common.status.medium",
  high: "common.status.high",
  stale: "common.status.stale",
  partial: "common.status.partial",
  trusted: "common.status.trusted",
  info: "common.status.info",
  warning: "common.status.warning",
  error: "common.status.error",
  ok: "common.status.ok",
  created: "common.status.created",
  started: "common.status.started",
  updated: "common.status.updated",
  due_changed: "common.status.due_changed",
  baseline_ready: "common.status.baseline_ready",
  removed: "common.status.removed",
  normal: "common.status.normal",
  high_attention: "common.status.high_attention",
  new_work: "common.status.new_work",
  proposal: "common.status.proposal",
  canonical: "common.status.canonical",
  gmail: "common.status.gmail",
  ics: "common.status.ics",
  email: "common.status.email",
  calendar: "common.status.calendar",
  initial_review: "common.status.initial_review",
  changes: "common.status.changes",
  sources: "common.status.sources",
  families: "common.status.families",
  manual: "common.status.manual",
  review_required: "common.status.review_required",
  completed: "common.status.completed",
  date_only: "common.status.date_only",
  datetime: "common.status.datetime",
  bootstrap: "common.status.bootstrap",
  replay: "common.status.replay",
  monitoring_live: "common.status.monitoring_live",
  attention_required: "common.status.attention_required",
  importing_baseline: "common.status.importing_baseline",
  needs_initial_review: "common.status.needs_initial_review",
  baseline_import: "common.status.baseline_import",
  stable: "common.status.stable",
  rebind_pending: "common.status.rebind_pending",
};

const FALLBACK_KEYS: Record<string, string> = {
  "not available": "common.labels.notAvailable",
  "unknown": "common.labels.unknown",
  "unknown course": "changes.unknownCourse",
  "unknown error": "common.labels.requestError",
  "recently": "common.labels.recent",
  "no sample": "common.labels.notAvailable",
  "unavailable": "common.labels.unavailable",
  "workspace": "common.labels.workspace",
  "no due date": "common.labels.noDueDate",
  "not connected": "common.status.disconnected",
  "n/a": "common.labels.notAvailable",
};

const LOADING_LABEL_KEYS: Record<string, string> = {
  overview: "common.loadingLabels.overview",
  sources: "common.loadingLabels.sources",
  changes: "common.loadingLabels.changes",
  "initial review": "common.loadingLabels.initialReview",
  settings: "common.loadingLabels.settings",
  onboarding: "common.loadingLabels.onboarding",
  families: "common.loadingLabels.families",
  "manual workspace": "common.loadingLabels.manualWorkspace",
  "mcp access": "common.loadingLabels.mcpAccess",
  "source detail": "common.loadingLabels.sourceDetail",
  "gmail setup": "common.loadingLabels.gmailSetup",
  "canvas ics setup": "common.loadingLabels.canvasIcsSetup",
  "proposal edit": "common.loadingLabels.proposalEdit",
  "suggestion edit": "common.loadingLabels.proposalEdit",
  "direct edit": "common.loadingLabels.directEdit",
};

export function setRuntimeLocale(locale: Locale) {
  runtimeLocale = locale;
}

export function getRuntimeLocale() {
  return runtimeLocale;
}

export function getDictionary(locale: Locale = runtimeLocale) {
  return dictionaries[locale];
}

export function translate(key: string, vars?: Record<string, Primitive>, locale: Locale = runtimeLocale) {
  const value = getByPath(getDictionary(locale), key);
  if (typeof value === "string") {
    return interpolate(value, vars);
  }
  return key;
}

export function translateArray<T = unknown>(key: string, locale: Locale = runtimeLocale) {
  const value = getByPath(getDictionary(locale), key);
  return Array.isArray(value) ? (value as T[]) : [];
}

export function intlDateLocale(locale: Locale = runtimeLocale) {
  return intlLocale(locale);
}

export function formatNumber(value: number, locale: Locale = runtimeLocale) {
  return new Intl.NumberFormat(intlDateLocale(locale)).format(value);
}

export function translateStatusLabel(value: string | null | undefined, fallback = "Unknown", locale: Locale = runtimeLocale) {
  if (!value) {
    return translateFallback(fallback, locale);
  }
  const normalized = value.trim().toLowerCase().replace(/\s+/g, "_");
  const key = STATUS_KEYS[normalized];
  if (key) {
    return translate(key, undefined, locale);
  }
  if (locale === "en") {
    return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
  }
  return value;
}

export function translateFallback(value: string, locale: Locale = runtimeLocale) {
  const key = FALLBACK_KEYS[value.trim().toLowerCase()];
  return key ? translate(key, undefined, locale) : value;
}

export function translateLoadingLabel(label: string, locale: Locale = runtimeLocale) {
  const normalized = label.trim().toLowerCase();
  const key = LOADING_LABEL_KEYS[normalized];
  return key ? translate(key, undefined, locale) : label;
}
