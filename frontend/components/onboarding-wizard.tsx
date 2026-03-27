"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { CalendarDays, Mailbox, RefreshCw } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ErrorState, LoadingState } from "@/components/data-states";
import {
  getOnboardingStatus,
  saveOnboardingCanvasIcs,
  saveOnboardingMonitoringWindow,
  skipOnboardingGmail,
  startOnboardingGmailOAuth,
} from "@/lib/api/onboarding";
import { translate } from "@/lib/i18n/runtime";
import { useApiResource } from "@/lib/use-api-resource";
import { workbenchPanelClassName, workbenchStateSurfaceClassName, workbenchSupportPanelClassName } from "@/lib/workbench-styles";
import type { OnboardingStage, OnboardingStatus } from "@/lib/types";

const stepOrder: Array<{
  id: "canvas" | "gmail" | "monitoring";
  title: string;
  description: string;
}> = [
  { id: "canvas", title: "onboarding.canvasStepTitle", description: "onboarding.canvasStepDescription" },
  { id: "gmail", title: "onboarding.gmailStepTitle", description: "onboarding.gmailStepDescription" },
  { id: "monitoring", title: "onboarding.monitoringStepTitle", description: "onboarding.monitoringStepDescription" },
];

function currentStepIndex(stage: OnboardingStage) {
  if (stage === "needs_canvas_ics") return 0;
  if (stage === "needs_gmail_or_skip") return 1;
  return 2;
}

function stageTitle() {
  return translate("onboarding.heroTitle");
}

function defaultMonitoringStart() {
  const now = new Date();
  now.setDate(now.getDate() - 90);
  return now.toISOString().slice(0, 10);
}

export function OnboardingWizard() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data, loading, error, refresh } = useApiResource<OnboardingStatus>(() => getOnboardingStatus(), []);
  const oauthStatus = searchParams.get("oauth_status");
  const oauthMessage = searchParams.get("message");
  const defaultStart = defaultMonitoringStart();
  const [canvasIcsUrl, setCanvasIcsUrl] = useState("");
  const [monitorSince, setMonitorSince] = useState("");
  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [savingCanvas, setSavingCanvas] = useState(false);
  const [startingGmail, setStartingGmail] = useState(false);
  const [skippingGmail, setSkippingGmail] = useState(false);
  const [savingMonitoring, setSavingMonitoring] = useState(false);

  useEffect(() => {
    if (!data) {
      return;
    }
    if (data.stage === "ready") {
      router.replace("/");
      return;
    }
    setMonitorSince((current) => current || data.monitoring_window?.monitor_since || defaultStart);
  }, [data, defaultStart, router]);

  useEffect(() => {
    if (!oauthStatus && !oauthMessage) {
      return;
    }
    let cancelled = false;
    const nextBanner =
      oauthStatus === "success"
        ? { tone: "info" as const, text: oauthMessage || translate("onboarding.oauthConnected") }
        : { tone: "error" as const, text: oauthMessage || translate("onboarding.oauthFailed") };
    setBanner(nextBanner);
    void refresh().finally(() => {
      if (cancelled) return;
      router.replace("/onboarding");
    });
    return () => {
      cancelled = true;
    };
  }, [oauthMessage, oauthStatus, refresh, router]);

  async function submitCanvasIcs() {
    if (!canvasIcsUrl.trim()) {
      return;
    }
    setSavingCanvas(true);
    setBanner(null);
    try {
      const next = await saveOnboardingCanvasIcs({ url: canvasIcsUrl.trim() });
      setCanvasIcsUrl("");
      setBanner({ tone: "info", text: next.message });
      if (next.stage === "ready") {
        router.replace("/");
        router.refresh();
        return;
      }
      await refresh();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("onboarding.saveCanvasError") });
    } finally {
      setSavingCanvas(false);
    }
  }

  async function connectGmail() {
    setStartingGmail(true);
    setBanner(null);
    try {
      const session = await startOnboardingGmailOAuth({ label_id: "INBOX" });
      window.location.assign(session.authorization_url);
    } catch (err) {
      setStartingGmail(false);
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("onboarding.startGmailError") });
    }
  }

  async function skipGmailStep() {
    setSkippingGmail(true);
    setBanner(null);
    try {
      const next = await skipOnboardingGmail();
      setBanner({ tone: "info", text: next.message });
      if (next.stage === "ready") {
        router.replace("/");
        router.refresh();
        return;
      }
      await refresh();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("onboarding.skipGmailError") });
    } finally {
      setSkippingGmail(false);
    }
  }

  async function submitMonitoringWindow() {
    if (!monitorSince) {
      return;
    }
    setSavingMonitoring(true);
    setBanner(null);
    try {
      const next = await saveOnboardingMonitoringWindow({
        monitor_since: monitorSince,
      });
      setBanner({ tone: "info", text: next.message });
      if (next.stage === "ready") {
        router.replace("/");
        router.refresh();
        return;
      }
      await refresh();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("onboarding.saveMonitoringError") });
    } finally {
      setSavingMonitoring(false);
    }
  }

  if (loading) {
    return <LoadingState label={translate("common.loadingLabels.onboarding")} />;
  }
  if (error) {
    return <ErrorState message={error} />;
  }
  if (!data) {
    return <ErrorState message={translate("onboarding.statusUnavailable")} />;
  }

  const stepIndex = currentStepIndex(data.stage);

  return (
    <div className="space-y-5" data-testid="onboarding-wizard">
      <Card className="relative overflow-hidden px-6 py-7 md:px-8 md:py-8">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.16),transparent_34%),radial-gradient(circle_at_82%_18%,rgba(215,90,45,0.14),transparent_28%)]" />
        <div className="relative max-w-4xl">
          <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">{translate("onboarding.introEyebrow")}</p>
          <h1 className="mt-3 text-3xl font-semibold text-ink md:text-4xl">{stageTitle()}</h1>
          <p className="mt-4 text-sm leading-7 text-[#596270]">
            {translate("onboarding.heroSummary")}
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Badge tone="pending">{translate("onboarding.onboardingRequired")}</Badge>
            <Badge tone="info">{translate("onboarding.currentStep", { step: stepIndex + 1, total: stepOrder.length })}</Badge>
            <Badge tone="default">{translate(stepOrder[stepIndex].title)}</Badge>
            {data.monitoring_window ? (
              <Badge tone="default">{translate("onboarding.monitoringFrom", { date: data.monitoring_window.monitor_since })}</Badge>
            ) : null}
          </div>
          <div className="mt-6 max-w-xl space-y-2">
            <div className="flex items-center justify-between gap-3 text-sm text-[#596270]">
              <span>{translate("onboarding.progress")}</span>
              <span>{Math.round(((stepIndex + (data.stage === "ready" ? 1 : 0)) / stepOrder.length) * 100)}%</span>
            </div>
            <div className="h-2 rounded-full bg-[rgba(20,32,44,0.08)]">
              <div
                className="h-2 rounded-full bg-cobalt transition-all duration-500"
                style={{ width: `${Math.min(((stepIndex + (data.stage === "ready" ? 1 : 0)) / stepOrder.length) * 100, 100)}%` }}
              />
            </div>
          </div>
        </div>
      </Card>

      {banner ? <Card className={workbenchStateSurfaceClassName(banner.tone === "error" ? "error" : "info", `p-4 text-sm ${banner.tone === "error" ? "text-[#7f3d2a]" : "text-[#314051]"}`)}>{banner.text}</Card> : null}

      {data.stage === "needs_canvas_ics" ? (
        <Card className="p-6 md:p-7">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(31,94,255,0.1)] text-cobalt">
              <CalendarDays className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">{translate("onboarding.required")}</p>
              <h2 className="mt-2 text-2xl font-semibold">{translate("onboarding.canvasTitle")}</h2>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                {translate("onboarding.canvasSummary")}
              </p>
            </div>
          </div>
          <div className="mt-6 space-y-4">
            <div className="space-y-3">
              <label className="block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="onboarding-canvas-ics">
                {translate("onboarding.canvasUrl")}
              </label>
              <Input
                id="onboarding-canvas-ics"
                placeholder={translate("onboarding.canvasPlaceholder")}
                value={canvasIcsUrl}
                onChange={(event) => setCanvasIcsUrl(event.target.value)}
              />
              <p className="text-xs leading-5 text-[#6d7885]">
                {translate("onboarding.canvasHelp")}
              </p>
              <Button className="w-full md:w-auto" disabled={savingCanvas || !canvasIcsUrl.trim()} onClick={() => void submitCanvasIcs()}>
                {savingCanvas ? translate("onboarding.saveCanvasBusy") : translate("onboarding.saveCanvas")}
              </Button>
            </div>
            <Card className={workbenchPanelClassName("quiet", "p-5")}>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("onboarding.canvasUrl")}</p>
              <p className="mt-3 text-base font-medium text-ink">{translate("onboarding.canvasGuideTitle")}</p>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                {translate("onboarding.canvasGuideSummary")}
              </p>
              <div className="mt-4">
                <Button asChild variant="soft">
                  <a href="https://canvas.ucsd.edu/calendar" target="_blank" rel="noreferrer noopener">
                    {translate("onboarding.openCanvasCalendar")}
                  </a>
                </Button>
              </div>
            </Card>
          </div>
        </Card>
      ) : null}

      {data.stage === "needs_gmail_or_skip" ? (
        <Card className="p-6 md:p-7">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(215,90,45,0.12)] text-ember">
              <Mailbox className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">{translate("onboarding.optional")}</p>
              <h2 className="mt-2 text-2xl font-semibold">{translate("onboarding.gmailTitle")}</h2>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                {translate("onboarding.gmailSummary")}
              </p>
            </div>
          </div>
          <div className="mt-6 space-y-4">
            <Card className={workbenchPanelClassName("secondary", "p-5")}>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("onboarding.gmailStepTitle")}</p>
              <p className="mt-3 text-base font-medium text-ink">
                {data.gmail_source?.connected && data.gmail_source.oauth_account_email
                  ? translate("onboarding.gmailConnectedAs", { email: data.gmail_source.oauth_account_email })
                  : translate("onboarding.gmailNotConnectedYet")}
              </p>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                {translate("onboarding.gmailOauthReturnHere")}
              </p>
              <div className="mt-5 flex flex-wrap gap-3">
                <Button disabled={startingGmail} onClick={() => void connectGmail()}>
                  {startingGmail ? translate("onboarding.startGmailBusy") : translate("onboarding.connectGmail")}
                </Button>
                <Button variant="ghost" disabled={skippingGmail} onClick={() => void skipGmailStep()}>
                  {skippingGmail ? translate("onboarding.skipGmailBusy") : translate("onboarding.skipGmail")}
                </Button>
              </div>
            </Card>
            <Card className={workbenchPanelClassName("quiet", "p-5")}>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("onboarding.optional")}</p>
              <p className="mt-3 text-sm leading-6 text-[#596270]">
                {translate("onboarding.gmailSkipLaterSummary")}
              </p>
            </Card>
          </div>
        </Card>
      ) : null}

      {data.stage === "needs_monitoring_window" ? (
        <Card className="p-6 md:p-7">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(31,94,255,0.1)] text-cobalt">
              <RefreshCw className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">{translate("onboarding.required")}</p>
              <h2 className="mt-2 text-2xl font-semibold">{translate("onboarding.monitoringTitle")}</h2>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                {translate("onboarding.monitoringSummary")}
              </p>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                {translate("onboarding.monitoringStartsAfterSave")}
              </p>
            </div>
          </div>
          <div className="mt-6 space-y-4">
            <div className="grid gap-4">
              <div>
                <label className="block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="monitor-since">
                  {translate("onboarding.monitorSince")}
                </label>
                <Input id="monitor-since" type="date" value={monitorSince} onChange={(event) => setMonitorSince(event.target.value)} />
                <p className="mt-2 text-xs leading-5 text-[#6d7885]">
                  {translate("onboarding.monitoringDefaultHint", { date: defaultStart })}
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <Button className="w-full md:w-auto" disabled={savingMonitoring || !monitorSince} onClick={() => void submitMonitoringWindow()}>
                  {savingMonitoring
                    ? translate("onboarding.saveMonitoringBusy")
                    : translate("onboarding.saveMonitoring")}
                </Button>
                {monitorSince !== defaultStart ? (
                  <Button variant="ghost" disabled={savingMonitoring} onClick={() => setMonitorSince(defaultStart)}>
                    {translate("onboarding.monitoringResetDefault")}
                  </Button>
                ) : null}
              </div>
            </div>
            <Card className={workbenchPanelClassName("quiet", "p-5")}>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("onboarding.monitoringStepTitle")}</p>
              <div className="mt-4 space-y-3 text-sm text-[#314051]">
                {(["0", "1", "2"] as const).map((index) => (
                  <p key={index}>{translate(`onboarding.monitoringGuideItems.${index}`)}</p>
                ))}
              </div>
              <p className="mt-5 text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("sources.listEyebrow")}</p>
              <div className="mt-3 space-y-3 text-sm text-[#314051]">
                <div className={workbenchSupportPanelClassName("default", "p-4")}>
                  <p className="font-medium text-ink">Canvas ICS</p>
                  <p className="mt-1 text-[#596270]">
                    {data.canvas_source?.connected ? translate("onboarding.sourceReady", { sourceId: data.canvas_source.source_id }) : translate("onboarding.sourceMissing")}
                  </p>
                </div>
                <div className={workbenchSupportPanelClassName("default", "p-4")}>
                  <p className="font-medium text-ink">Gmail</p>
                  <p className="mt-1 text-[#596270]">
                    {data.gmail_source?.connected
                      ? data.gmail_source.oauth_account_email || translate("onboarding.sourceReady", { sourceId: data.gmail_source.source_id })
                      : data.gmail_skipped
                        ? translate("onboarding.gmailSkippedForSetup")
                        : translate("onboarding.gmailNotConnectedYet")}
                  </p>
                </div>
              </div>
            </Card>
          </div>
        </Card>
      ) : null}

      <Card className={workbenchPanelClassName("secondary", "p-5 text-sm text-[#596270]")}>
        {translate("onboarding.manageLaterSummary")}{" "}
        <Link href="/sources" className="font-medium text-cobalt">{translate("shell.nav.sources.label")}</Link>.
      </Card>
    </div>
  );
}
