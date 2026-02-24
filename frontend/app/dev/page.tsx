"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { FlaskConical, Loader2 } from "lucide-react";

import { DashboardPage, DashboardPageHeader } from "@/components/dashboard/page-shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiRequest, getOnboardingStatus } from "@/lib/api";
import { getRuntimeConfig } from "@/lib/config";

export default function DevPage() {
  const config = useMemo(() => getRuntimeConfig(), []);
  const [subject, setSubject] = useState("[DEMO] CSE 151A Homework deadline moved");
  const [fromValue, setFromValue] = useState("instructor@example.edu");
  const [bodyText, setBodyText] = useState("Homework 2 deadline changed from Friday 5pm to Sunday 11:59pm.");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const enabled = Boolean(config.enableDevEndpoints && (config.appEnv ?? "").toLowerCase() === "dev");

  useEffect(() => {
    if (!config.apiKey) {
      return;
    }
    void (async () => {
      try {
        const status = await getOnboardingStatus(config);
        if (status.stage !== "ready") {
          window.location.replace("/ui/onboarding");
        }
      } catch (err) {
        window.location.replace("/ui/onboarding");
      }
    })();
  }, [config]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!enabled || busy) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await apiRequest<{ ui_path: string }>(config, "/v1/dev/inject_notify", {
        method: "POST",
        body: JSON.stringify({
          subject: subject.trim(),
          from: fromValue.trim() || null,
          date: new Date().toISOString(),
          body_text: bodyText.trim(),
          course_hints: ["DEMO"],
          event_type: "deadline",
          action_items: [
            {
              action: "Check updated deadline",
              due_iso: null,
              where: null,
            },
          ],
        }),
      });
      window.location.assign(response.ui_path || "/ui/feed");
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <DashboardPage maxWidthClassName="max-w-3xl">
      <DashboardPageHeader
        icon={FlaskConical}
        title="Dev Tools"
        description="Inject one demo notify item from email-like text for UI verification."
        current="dev"
        activeInputId={null}
        showDev={enabled}
        navDensity="compact"
      />

      {!enabled ? (
        <Alert>
          <AlertTitle>Dev endpoint disabled</AlertTitle>
          <AlertDescription>Set APP_ENV=dev and ENABLE_DEV_ENDPOINTS=true to use this page.</AlertDescription>
        </Alert>
      ) : (
        <Card className="animate-in">
          <CardHeader>
            <CardTitle>Inject Demo Notify</CardTitle>
            <CardDescription>Creates one KEEP+notify record and redirects to feed after success.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={(event) => void onSubmit(event)}>
              <div className="space-y-2">
                <Label htmlFor="dev-subject">Subject</Label>
                <Input id="dev-subject" value={subject} onChange={(event) => setSubject(event.target.value)} required />
              </div>
              <div className="space-y-2">
                <Label htmlFor="dev-from">From</Label>
                <Input id="dev-from" value={fromValue} onChange={(event) => setFromValue(event.target.value)} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="dev-body">Body</Label>
                <Textarea id="dev-body" className="min-h-28" value={bodyText} onChange={(event) => setBodyText(event.target.value)} required />
              </div>
              {error ? (
                <Alert>
                  <AlertTitle>Inject failed</AlertTitle>
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              ) : null}
              <Button type="submit" disabled={busy || !subject.trim() || !bodyText.trim()}>
                {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                Inject and open Feed
              </Button>
            </form>
          </CardContent>
        </Card>
      )}
    </DashboardPage>
  );
}
