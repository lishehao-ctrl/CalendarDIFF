"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { CalendarDays, CheckCircle2, Mailbox, ArrowRight, RefreshCw } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ErrorState, LoadingState } from "@/components/data-states";
import {
  getOnboardingStatus,
  saveOnboardingCanvasIcs,
  saveOnboardingTermBinding,
  skipOnboardingGmail,
  startOnboardingGmailOAuth,
} from "@/lib/api/onboarding";
import { useApiResource } from "@/lib/use-api-resource";
import type { OnboardingStage, OnboardingStatus } from "@/lib/types";

const stepOrder: Array<{
  id: "canvas" | "gmail" | "term";
  title: string;
  description: string;
}> = [
  { id: "canvas", title: "Canvas ICS", description: "Required intake source" },
  { id: "gmail", title: "Gmail", description: "Optional email lane" },
  { id: "term", title: "Term", description: "Processing window" },
];

function currentStepIndex(stage: OnboardingStage) {
  if (stage === "needs_canvas_ics") return 0;
  if (stage === "needs_gmail_or_skip") return 1;
  return 2;
}

function stageTitle(stage: OnboardingStage) {
  if (stage === "needs_term_renewal") {
    return "Set the next term before you continue.";
  }
  return "Connect sources once, then enter the review workspace with the right scope.";
}

export function OnboardingWizard() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data, loading, error, refresh } = useApiResource<OnboardingStatus>(() => getOnboardingStatus(), []);
  const [canvasIcsUrl, setCanvasIcsUrl] = useState("");
  const [termKey, setTermKey] = useState("");
  const [termFrom, setTermFrom] = useState("");
  const [termTo, setTermTo] = useState("");
  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [savingCanvas, setSavingCanvas] = useState(false);
  const [startingGmail, setStartingGmail] = useState(false);
  const [skippingGmail, setSkippingGmail] = useState(false);
  const [savingTerm, setSavingTerm] = useState(false);

  useEffect(() => {
    if (!data) {
      return;
    }
    if (data.stage === "ready") {
      router.replace("/");
      return;
    }
    if (data.term_binding) {
      setTermKey((current) => current || data.term_binding?.term_key || "");
      setTermFrom((current) => current || data.term_binding?.term_from || "");
      setTermTo((current) => current || data.term_binding?.term_to || "");
    }
  }, [data, router]);

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

  async function submitTerm() {
    if (!termFrom || !termTo) {
      return;
    }
    setSavingTerm(true);
    setBanner(null);
    try {
      const next = await saveOnboardingTermBinding({
        term_key: termKey.trim() || null,
        term_from: termFrom,
        term_to: termTo,
      });
      setBanner({ tone: "info", text: next.message });
      if (next.stage === "ready") {
        router.replace("/");
        router.refresh();
        return;
      }
      await refresh();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to save the term window." });
    } finally {
      setSavingTerm(false);
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
            <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">Setup</p>
            <h1 className="mt-3 text-3xl font-semibold text-ink md:text-4xl">{stageTitle(data.stage)}</h1>
            <p className="mt-4 text-sm leading-7 text-[#596270]">
              CalendarDIFF now treats your term as a real processing boundary. Set up the required sources, decide whether Gmail should join this term, and then save the term window once.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Badge tone="pending">
                {data.stage === "needs_term_renewal" ? "Term renewal required" : "Onboarding required"}
              </Badge>
              {data.term_binding ? (
                <Badge tone="default">
                  Current term {data.term_binding.term_from} to {data.term_binding.term_to}
                </Badge>
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
                  (step.id === "term" && !!data.term_binding && data.stage === "ready");
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
                You can find this on the Canvas Calendar page. Once this is saved, Gmail becomes optional and the term step unlocks after that.
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
              <h2 className="mt-2 text-2xl font-semibold">Decide whether Gmail joins this term</h2>
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
                The OAuth callback will return you here. If you connect Gmail now, it will use the same term scope once the term step is saved.
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
                You can still enter the dashboard with Canvas only. Later, if you decide to add Gmail from Sources, it will inherit the active term automatically.
              </p>
            </Card>
          </div>
        </Card>
      ) : null}

      {(data.stage === "needs_term_binding" || data.stage === "needs_term_renewal") ? (
        <Card className="p-6 md:p-7">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(31,94,255,0.1)] text-cobalt">
              <RefreshCw className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">
                {data.stage === "needs_term_renewal" ? "Renewal required" : "Required"}
              </p>
              <h2 className="mt-2 text-2xl font-semibold">
                {data.stage === "needs_term_renewal" ? "Choose the next term window" : "Set the term window"}
              </h2>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                This window decides which Gmail and Canvas content is monitored for the current workspace. `term_key` is optional and mainly useful if you want a friendlier management label.
              </p>
            </div>
          </div>
          <div className="mt-6 grid gap-5 xl:grid-cols-[1fr_320px]">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="md:col-span-2">
                <label className="block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="term-key">
                  Term key (optional)
                </label>
                <Input id="term-key" placeholder="WI26" value={termKey} onChange={(event) => setTermKey(event.target.value)} />
              </div>
              <div>
                <label className="block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="term-from">
                  Term from
                </label>
                <Input id="term-from" type="date" value={termFrom} onChange={(event) => setTermFrom(event.target.value)} />
              </div>
              <div>
                <label className="block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="term-to">
                  Term to
                </label>
                <Input id="term-to" type="date" value={termTo} onChange={(event) => setTermTo(event.target.value)} />
              </div>
              <div className="md:col-span-2">
                <Button className="w-full md:w-auto" disabled={savingTerm || !termFrom || !termTo} onClick={() => void submitTerm()}>
                  {savingTerm
                    ? (data.stage === "needs_term_renewal" ? "Renewing term..." : "Saving term...")
                    : (data.stage === "needs_term_renewal" ? "Renew term" : "Save term and continue")}
                </Button>
              </div>
            </div>
            <Card className="bg-white/60 p-5">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Connected sources</p>
              <div className="mt-4 space-y-3 text-sm text-[#314051]">
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
        Need to manage sources after setup? You can do that later from <Link href="/sources" className="font-medium text-cobalt">Sources</Link>, but the dashboard only unlocks once the required onboarding step finishes.
      </Card>
    </div>
  );
}
