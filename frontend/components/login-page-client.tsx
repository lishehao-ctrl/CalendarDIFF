"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { PublicAuthShell } from "@/components/public-auth-shell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { login, register } from "@/lib/api/auth";
import { translate } from "@/lib/i18n/runtime";
import { useLocale } from "@/lib/i18n/use-locale";
import { usePageMetadata } from "@/lib/use-page-metadata";
import { workbenchStateSurfaceClassName } from "@/lib/workbench-styles";

export function LoginPageClient({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const { locale, setLocale } = useLocale();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const t = (key: string, vars?: Record<string, string | number | null | undefined>) =>
    translate(key, vars, locale);
  const pageTitle = mode === "login" ? t("auth.signIn") : t("auth.register");
  const pageSummary = mode === "login" ? t("auth.loginSummary") : t("auth.registerSummary");

  usePageMetadata(pageTitle, pageSummary);

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      if (mode === "register" && password !== confirmPassword) {
        throw new Error(t("auth.passwordsDoNotMatch"));
      }
      if (mode === "login") {
        await login({ email, password, language_code: locale });
      } else {
        await register({ email, password, language_code: locale });
      }
      router.replace("/onboarding");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : mode === "login" ? t("auth.unableToLogin") : t("auth.unableToRegister"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <PublicAuthShell locale={locale} onLocaleChange={setLocale}>
      <Card className="p-8 md:p-10">
        <p className="text-xs uppercase tracking-[0.24em] text-[#6d7885]">{mode === "login" ? t("auth.welcomeBack") : t("auth.createAccountEyebrow")}</p>
        <h2 className="mt-3 text-3xl font-semibold text-ink">{pageTitle}</h2>
        <p className="mt-3 text-sm leading-6 text-[#596270]">
          {pageSummary}
        </p>
        {error ? (
          <div className={workbenchStateSurfaceClassName("error", "mt-5 px-4 py-3 text-sm text-[#7f3d2a]")}>
            {error}
          </div>
        ) : null}
        <form
          className="mt-6 space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <div>
            <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="email-auth">
              {t("auth.email")}
            </label>
            <Input id="email-auth" value={email} onChange={(event) => setEmail(event.target.value)} placeholder={t("auth.emailPlaceholder")} />
          </div>
          <div>
            <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="password-auth">
              {t("auth.password")}
            </label>
            <Input
              id="password-auth"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={mode === "register" ? t("auth.passwordRegisterPlaceholder") : t("auth.passwordLoginPlaceholder")}
            />
          </div>
          {mode === "register" ? (
            <div>
              <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="password-confirm-auth">
                {t("auth.confirmPassword")}
              </label>
              <Input id="password-confirm-auth" type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} placeholder={t("auth.confirmPasswordPlaceholder")} />
            </div>
          ) : null}
          <Button type="submit" className="w-full" disabled={submitting || !email || !password || (mode === "register" && !confirmPassword)}>
            {submitting
              ? (mode === "login" ? t("auth.signInBusy") : t("auth.createAccountBusy"))
              : (mode === "login" ? t("auth.signIn") : t("auth.createAccountEyebrow"))}
          </Button>
        </form>
        <div className="mt-6 space-y-3 text-sm text-[#596270]">
          <div>
            {mode === "login" ? (
              <>
                {t("auth.needAccount")} <Link className="font-medium text-cobalt" href="/register">{t("auth.register")}</Link>
              </>
            ) : (
              <>
                {t("auth.alreadyRegistered")} <Link className="font-medium text-cobalt" href="/login">{t("auth.signIn")}</Link>
              </>
            )}
          </div>
          <div>
            {t("auth.openPreview")} <Link className="font-medium text-cobalt" href="/preview">{t("auth.openPreviewLink")}</Link>
          </div>
          <div className="flex flex-wrap gap-3 text-xs uppercase tracking-[0.14em] text-[#6d7885]">
            <Link className="font-medium text-[#425061] transition hover:text-cobalt" href="/privacy">{t("auth.privacy")}</Link>
            <span aria-hidden="true">•</span>
            <Link className="font-medium text-[#425061] transition hover:text-cobalt" href="/terms">{t("auth.terms")}</Link>
          </div>
        </div>
      </Card>
    </PublicAuthShell>
  );
}
