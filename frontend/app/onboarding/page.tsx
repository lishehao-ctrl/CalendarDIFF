"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { Loader2, UserRoundPlus } from "lucide-react";

import { getOnboardingStatus, registerOnboarding } from "@/lib/api";
import { getRuntimeConfig } from "@/lib/config";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { OnboardingStatus } from "@/lib/types";

export default function OnboardingPage() {
  const config = useMemo(() => getRuntimeConfig(), []);
  const [notifyEmail, setNotifyEmail] = useState("");
  const [icsUrl, setIcsUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusInfo, setStatusInfo] = useState<OnboardingStatus | null>(null);

  useEffect(() => {
    if (!config.apiKey) {
      setError("Missing API key from /ui/app-config.js");
      setChecking(false);
      return;
    }

    void (async () => {
      try {
        const status = await getOnboardingStatus(config);
        setStatusInfo(status);
        if (status.stage === "ready") {
          window.location.replace("/ui/processing");
          return;
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setChecking(false);
      }
    })();
  }, [config]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!config.apiKey || busy) {
      return;
    }
    if (!notifyEmail.trim() || !icsUrl.trim()) {
      setError("notify_email and ICS URL are required.");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      await registerOnboarding(config, {
        notify_email: notifyEmail.trim(),
        ics: {
          url: icsUrl.trim(),
        },
      });
      window.location.replace("/ui/processing");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="container py-6">
      <div className="mx-auto max-w-xl space-y-4">
        <Card className="animate-in">
          <CardHeader>
            <CardTitle className="inline-flex items-center gap-2 text-2xl [font-family:var(--font-heading)]">
              <UserRoundPlus className="h-5 w-5 text-accent" />
              Onboarding Required
            </CardTitle>
            <CardDescription>
              Bind notify email + first ICS URL, then run the initial baseline sync before entering Processing workspace.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {checking ? (
              <div className="flex items-center text-sm text-muted">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Checking initialization status...
              </div>
            ) : (
              <form className="space-y-4" onSubmit={(event) => void onSubmit(event)}>
                <div className="space-y-2">
                  <Label htmlFor="onboarding-notify-email">Notify Email</Label>
                  <Input
                    id="onboarding-notify-email"
                    type="email"
                    value={notifyEmail}
                    onChange={(event) => setNotifyEmail(event.target.value)}
                    placeholder="student@example.com"
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="onboarding-ics-url">ICS URL</Label>
                  <Input
                    id="onboarding-ics-url"
                    type="url"
                    value={icsUrl}
                    onChange={(event) => setIcsUrl(event.target.value)}
                    placeholder="https://example.edu/calendar.ics"
                    required
                  />
                </div>
                {statusInfo ? (
                  <Alert>
                    <AlertTitle>Current Stage: {statusInfo.stage}</AlertTitle>
                    <AlertDescription>{statusInfo.message}</AlertDescription>
                  </Alert>
                ) : null}
                {error ? (
                  <Alert>
                    <AlertTitle>Onboarding failed</AlertTitle>
                    <AlertDescription>{error}</AlertDescription>
                  </Alert>
                ) : null}
                <Button type="submit" disabled={busy}>
                  {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Register and Run Initial Baseline
                </Button>
              </form>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
