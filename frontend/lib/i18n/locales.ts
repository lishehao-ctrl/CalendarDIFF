export const LOCALE_STORAGE_KEY = "calendardiff.locale";
export const LOCALE_COOKIE_KEY = "calendardiff_locale";

export const SUPPORTED_LOCALES = ["en", "zh-CN"] as const;

export type Locale = (typeof SUPPORTED_LOCALES)[number];

export function isSupportedLocale(value: string | null | undefined): value is Locale {
  return value === "en" || value === "zh-CN";
}

export function normalizeLocale(value: string | null | undefined): Locale | null {
  if (!value) {
    return null;
  }
  if (isSupportedLocale(value)) {
    return value;
  }
  const normalized = value.toLowerCase();
  if (normalized.startsWith("zh")) {
    return "zh-CN";
  }
  if (normalized.startsWith("en")) {
    return "en";
  }
  return null;
}

export function detectBrowserLocale(): Locale {
  if (typeof navigator === "undefined") {
    return "en";
  }
  const candidates = [...(navigator.languages || []), navigator.language];
  for (const candidate of candidates) {
    const locale = normalizeLocale(candidate);
    if (locale) {
      return locale;
    }
  }
  return "en";
}

export function resolveStoredLocale(): Locale | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return normalizeLocale(window.localStorage.getItem(LOCALE_STORAGE_KEY));
  } catch {
    return null;
  }
}

export function resolvePreferredLocale(): Locale {
  return resolveStoredLocale() || detectBrowserLocale() || "en";
}

export function intlLocale(locale: Locale) {
  return locale === "zh-CN" ? "zh-CN" : "en-US";
}
