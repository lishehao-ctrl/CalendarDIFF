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
  stale: "common.status.stale",
  partial: "common.status.partial",
  trusted: "common.status.trusted",
  info: "common.status.info",
  warning: "common.status.warning",
  error: "common.status.error",
  ok: "common.status.ok",
  created: "common.status.created",
  updated: "common.status.updated",
  due_changed: "common.status.due_changed",
  removed: "common.status.removed",
  proposal: "common.status.proposal",
  canonical: "common.status.canonical",
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
};

const FALLBACK_KEYS: Record<string, string> = {
  "Not available": "common.labels.notAvailable",
  "Unknown": "common.labels.unknown",
  "recently": "common.labels.recent",
  "No sample": "common.labels.notAvailable",
  "Unavailable": "common.labels.unavailable",
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
  const key = FALLBACK_KEYS[value];
  return key ? translate(key, undefined, locale) : value;
}

export function translateLoadingLabel(label: string, locale: Locale = runtimeLocale) {
  const normalized = label.trim().toLowerCase();
  const key = LOADING_LABEL_KEYS[normalized];
  return key ? translate(key, undefined, locale) : label;
}
