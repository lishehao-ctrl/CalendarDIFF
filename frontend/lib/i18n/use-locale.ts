"use client";

import { useLocaleContext, useT } from "@/lib/i18n/provider";

export function useLocale() {
  const { locale, setLocale, dictionary } = useLocaleContext();
  return { locale, setLocale, dictionary };
}

export { useT };
