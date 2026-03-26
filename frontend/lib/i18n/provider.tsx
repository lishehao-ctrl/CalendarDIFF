"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { dictionaries, getDictionary, setRuntimeLocale, translate, type Dictionary } from "@/lib/i18n/runtime";
import { LOCALE_COOKIE_KEY, LOCALE_STORAGE_KEY, resolvePreferredLocale, type Locale } from "@/lib/i18n/locales";

type LocaleContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  dictionary: Dictionary;
};

const LocaleContext = createContext<LocaleContextValue | null>(null);

export function LocaleProvider({
  children,
  initialLocale = "en",
}: {
  children: React.ReactNode;
  initialLocale?: Locale;
}) {
  const [locale, setLocale] = useState<Locale>(initialLocale);
  const [localeResolved, setLocaleResolved] = useState(false);

  // Keep non-hook formatters and translators in sync during render.
  setRuntimeLocale(locale);

  useEffect(() => {
    const preferred = resolvePreferredLocale();
    let cancelled = false;
    const timeoutId = window.setTimeout(() => {
      if (cancelled) {
        return;
      }
      setLocale((current) => (current === preferred ? current : preferred));
      setLocaleResolved(true);
    }, 0);

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, []);

  useEffect(() => {
    if (!localeResolved) {
      return;
    }
    if (typeof document !== "undefined") {
      document.documentElement.lang = locale;
    }
    if (typeof window !== "undefined") {
      try {
        window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
      } catch {
        // Ignore local storage write failures.
      }
    }
    if (typeof document !== "undefined") {
      document.cookie = `${LOCALE_COOKIE_KEY}=${encodeURIComponent(locale)}; path=/; max-age=31536000; samesite=lax`;
    }
  }, [locale, localeResolved]);

  const value = useMemo(
    () => ({
      locale,
      setLocale,
      dictionary: getDictionary(locale),
    }),
    [locale],
  );

  return (
    <LocaleContext.Provider value={value}>
      <div className="contents">{children}</div>
    </LocaleContext.Provider>
  );
}

export function useLocaleContext() {
  const context = useContext(LocaleContext);
  if (!context) {
    throw new Error("useLocaleContext must be used within LocaleProvider");
  }
  return context;
}

export function useT() {
  const { locale } = useLocaleContext();
  return (key: string, vars?: Record<string, string | number | null | undefined>) => translate(key, vars, locale);
}

export { dictionaries };
