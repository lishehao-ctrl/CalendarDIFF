"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { CalendarDays, CheckCircle2, Mailbox, RefreshCw } from "lucide-react";
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
import { useApiResource } from "@/lib/use-api-resource";
import type { OnboardingStage, OnboardingStatus } from "@/lib/types";

const stepOrder: Array<{
  id: "canvas" | "gmail" | "monitoring";
  title: string;
  description: string;
}> = [
  { id: "canvas", title: "Canvas ICS", description: "Required intake source" },
  { id: "gmail", title: "Gmail", description: "Optional email lane" },
  { id: "monitoring", title: "Monitoring", description: "How far back to include" },
];

function currentStepIndex(stage: OnboardingStage) {
  if (stage === "needs_canvas_ics") return 0;
  if (stage === "needs_gmail_or_skip") return 1;
  return 2;
}

function stageTitle() {
  return "Connect sources once, then enter the workspace with the right scope.";
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
    const oauthStatus = searchParams.get("oauth_status");
    const message = searchParams.get("message");
    if (!oauthStatus && !message) {
      return;
    }
    if (oauthStatus === "success") {
      setBanner({ tone: "info", text: message || "Gmail connected. Finish the next setup step to continue." });
      void refresh();
      return;
    }
    setBanner({ tone: "error", text: message || "OAuth did not complete." });
  }, [refresh, searchParams]);

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
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to save Canvas ICS." });
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
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to start Gmail OAuth." });
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
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to skip Gmail for now." });
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
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to save the monitoring window." });
    } finally {
      setSavingMonitoring(false);
    }
  }

  if (loading) {
    return <LoadingState label="onboarding" />;
  }
  if (error) {
    return <ErrorState message={error} />;
  }
  if (!data) {
    return <ErrorState message="Onboarding status is unavailable." />;
  }

  const stepIndex = currentStepIndex(data.stage);

  return (
    <div className="space-y-5">
      <Card className="relative overflow-hidden px-6 py-7 md:px-8 md:py-8">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.16),transparent_34%),radial-gradient(circle_at_82%_18%,rgba(215,90,45,0.14),transparent_28%)]" />
        <div className="relative grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
          <div className="max-w-3xl">
            <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">Onboarding</p>
            <h1 className="mt-3 text-3xl font-semibold text-ink md:text-4xl">{stageTitle()}</h1>
            <p className="mt-4 text-sm leading-7 text-[#596270]">
              Connect the required sources, decide whether Gmail joins, and choose how far back CalendarDIFF should start monitoring this workspace.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Badge tone="pending">Onboarding required</Badge>
              {data.monitoring_window ? (
                <Badge tone="default">Monitoring from {data.monitoring_window.monitor_since}</Badge>
              ) : null}
            </div>
          </div>
          <Card className="relative border-white/40 bg-white/55 p-5">
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Progress</p>
            <div className="mt-4 space-y-3">
              {stepOrder.map((step, index) => {
                const active = index === stepIndex;
                const complete =
                  (step.id === "canvas" && !!data.canvas_source?.connected) ||
                  (step.id === "gmail" && (!!data.gmail_source?.connected || data.gmail_skipped || stepIndex > 1)) ||
                  (step.id === "monitoring" && !!data.monitoring_window && data.stage === "ready");
                return (
                  <div key={step.id} className="flex items-start gap-3 rounded-[1.1rem] border border-line/80 bg-white/70 p-3">
                    <div className={`mt-0.5 flex h-8 w-8 items-center justify-center rounded-2xl ${complete ? "bg-[rgba(77,124,15,0.12)] text-moss" : active ? "bg-[rgba(31,94,255,0.12)] text-cobalt" : "bg-[rgba(20,32,44,0.06)] text-[#6d7885]"}`}>
                      {complete ? <CheckCircle2 className="h-4 w-4" /> : <span className="text-xs font-semibold">{index + 1}</span>}
                    </div>
                    <div>
                      <p className="font-medium text-ink">{step.title}</p>
                      <p className="mt-1 text-sm text-[#596270]">{step.description}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>
        </div>
      </Card>

      {banner ? (
        <Card className={banner.tone === "error" ? "border-[#efc4b5] bg-[#fff3ef] p-4 text-sm text-[#7f3d2a]" : "border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] p-4 text-sm text-[#314051]"}>
          {banner.text}
        </Card>
      ) : null}

      {data.stage === "needs_canvas_ics" ? (
        <Card className="p-6 md:p-7">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(31,94,255,0.1)] text-cobalt">
              <CalendarDays className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Required</p>
              <h2 className="mt-2 text-2xl font-semibold">Connect your Canvas ICS link</h2>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                This is the required intake source for every workspace. Grab your personal calendar feed from Canvas and paste the full ICS URL here.
              </p>
            </div>
          </div>
          <div className="mt-6 grid gap-5 xl:grid-cols-[1fr_320px]">
            <div className="space-y-3">
              <label className="block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="onboarding-canvas-ics">
                Canvas ICS URL
              </label>
              <Input
                id="onboarding-canvas-ics"
                placeholder="https://canvas.ucsd.edu/feeds/calendars/user_12345.ics"
                value={canvasIcsUrl}
                onChange={(event) => setCanvasIcsUrl(event.target.value)}
              />
              <p className="text-xs leading-5 text-[#6d7885]">
                You can find this on the Canvas Calendar page. Once this is saved, Gmail becomes optional and the monitoring step unlocks after that.
              </p>
              <Button className="w-full md:w-auto" disabled={savingCanvas || !canvasIcsUrl.trim()} onClick={() => void submitCanvasIcs()}>
                {savingCanvas ? "Saving Canvas ICS..." : "Save Canvas ICS"}
              </Button>
            </div>
            <Card className="bg-white/60 p-5">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Need the link?</p>
              <p className="mt-3 text-base font-medium text-ink">Open Canvas Calendar in a new tab.</p>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                Canvas exposes your personal ICS feed from the Calendar page. Copy the URL there, then come back and paste it here.
              </p>
              <div className="mt-4">
                <a
                  href="https://canvas.ucsd.edu/calendar"
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-flex h-10 items-center justify-center rounded-full bg-cobalt-soft px-4 text-sm font-medium text-cobalt transition-all duration-200 hover:bg-[rgba(31,94,255,0.16)]"
                >
                  Open Canvas Calendar
                </a>
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
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Optional</p>
              <h2 className="mt-2 text-2xl font-semibold">Decide whether Gmail joins this workspace</h2>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                Gmail adds email-only deadline changes and directive-style notices. You can connect it now or skip it and continue with Canvas only.
              </p>
            </div>
          </div>
          <div className="mt-6 grid gap-5 xl:grid-cols-[1fr_320px]">
            <Card className="bg-white/60 p-5">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Gmail</p>
              <p className="mt-3 text-base font-medium text-ink">
                {data.gmail_source?.connected && data.gmail_source.oauth_account_email
                  ? `Connected as ${data.gmail_source.oauth_account_email}`
                  : "No mailbox connected yet"}
              </p>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                The OAuth callback will return you here. If you connect Gmail now, it will use the same monitoring start once the last step is saved.
              </p>
              <div className="mt-5 flex flex-wrap gap-3">
                <Button disabled={startingGmail} onClick={() => void connectGmail()}>
                  {startingGmail ? "Redirecting to Google..." : "Connect Gmail"}
                </Button>
                <Button variant="ghost" disabled={skippingGmail} onClick={() => void skipGmailStep()}>
                  {skippingGmail ? "Skipping..." : "Skip for now"}
                </Button>
              </div>
            </Card>
            <Card className="bg-white/60 p-5">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">What happens if you skip?</p>
              <p className="mt-3 text-sm leading-6 text-[#596270]">
                You can still enter the workspace with Canvas only. Later, if you decide to add Gmail from Sources, it will inherit the same monitoring start automatically.
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
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Required</p>
              <h2 className="mt-2 text-2xl font-semibold">Choose how far back to monitor</h2>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                CalendarDIFF defaults to the last 90 days. Move this earlier if you want older assignments, exams, or project changes included on first sync.
              </p>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                Nothing starts syncing until you save this step.
              </p>
            </div>
          </div>
          <div className="mt-6 grid gap-5 xl:grid-cols-[1fr_320px]">
            <div className="grid gap-4">
              <div>
                <label className="block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="monitor-since">
                  Start monitoring from
                </label>
                <Input id="monitor-since" type="date" value={monitorSince} onChange={(event) => setMonitorSince(event.target.value)} />
                <p className="mt-2 text-xs leading-5 text-[#6d7885]">
                  Recommended default: {defaultStart}. Choose an earlier date only if you want to pull in older coursework or older email changes.
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <Button className="w-full md:w-auto" disabled={savingMonitoring || !monitorSince} onClick={() => void submitMonitoringWindow()}>
                  {savingMonitoring
                    ? "Saving monitoring window..."
                    : monitorSince === defaultStart
                      ? "Use last 90 days and continue"
                      : "Save custom start date and continue"}
                </Button>
                {monitorSince !== defaultStart ? (
                  <Button variant="ghost" disabled={savingMonitoring} onClick={() => setMonitorSince(defaultStart)}>
                    Reset to last 90 days
                  </Button>
                ) : null}
              </div>
            </div>
            <Card className="bg-white/60 p-5">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">What this controls</p>
              <div className="mt-4 space-y-3 text-sm text-[#314051]">
                <p>Default setup starts 90 days back.</p>
                <p>Choose an earlier date if you need older coursework or prior changes pulled into the workspace.</p>
                <p>This is a monitoring scope, not a semester label. Future updates still appear normally.</p>
              </div>
              <p className="mt-5 text-xs uppercase tracking-[0.18em] text-[#6d7885]">Connected sources</p>
              <div className="mt-3 space-y-3 text-sm text-[#314051]">
                <div className="rounded-[1rem] border border-line/80 bg-white/70 p-4">
                  <p className="font-medium text-ink">Canvas ICS</p>
                  <p className="mt-1 text-[#596270]">
                    {data.canvas_source?.connected ? `Ready on source #${data.canvas_source.source_id}` : "Missing"}
                  </p>
                </div>
                <div className="rounded-[1rem] border border-line/80 bg-white/70 p-4">
                  <p className="font-medium text-ink">Gmail</p>
                  <p className="mt-1 text-[#596270]">
                    {data.gmail_source?.connected
                      ? data.gmail_source.oauth_account_email || `Connected on source #${data.gmail_source.source_id}`
                      : data.gmail_skipped
                        ? "Skipped for this setup"
                        : "Not connected"}
                  </p>
                </div>
              </div>
            </Card>
          </div>
        </Card>
      ) : null}

      <Card className="p-5 text-sm text-[#596270]">
        Need to manage sources after onboarding? You can do that later from <Link href="/sources" className="font-medium text-cobalt">Sources</Link>, but the main workspace only opens once the required onboarding step finishes.
      </Card>
    </div>
  );
}
