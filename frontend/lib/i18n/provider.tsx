"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { dictionaries, getDictionary, setRuntimeLocale, translate, type Dictionary } from "@/lib/i18n/runtime";
import { LOCALE_STORAGE_KEY, resolvePreferredLocale, type Locale } from "@/lib/i18n/locales";

type LocaleContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  dictionary: Dictionary;
};

const LocaleContext = createContext<LocaleContextValue | null>(null);

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocale] = useState<Locale>("en");

  // Keep non-hook formatters and translators in sync during render.
  setRuntimeLocale(locale);

  useEffect(() => {
    const preferred = resolvePreferredLocale();
    setLocale((current) => (current === preferred ? current : preferred));
  }, []);

  useEffect(() => {
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
  }, [locale]);

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
      <div key={locale} className="contents">
        {children}
      </div>
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
