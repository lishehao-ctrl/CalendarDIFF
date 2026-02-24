"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { Loader2, UserRoundPlus } from "lucide-react";

import { ApiError, apiRequest } from "@/lib/api";
import { getRuntimeConfig } from "@/lib/config";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function OnboardingPage() {
  const config = useMemo(() => getRuntimeConfig(), []);
  const [notifyEmail, setNotifyEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!config.apiKey) {
      setError("Missing API key from /ui/app-config.js");
      setChecking(false);
      return;
    }

    void (async () => {
      try {
        await apiRequest(config, "/v1/user");
        window.location.replace("/ui/inputs");
      } catch (err) {
        if (isUserNotInitializedError(err)) {
          setChecking(false);
          return;
        }
        setError(err instanceof Error ? err.message : String(err));
        setChecking(false);
      }
    })();
  }, [config]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!config.apiKey || busy) {
      return;
    }
    if (!notifyEmail.trim()) {
      setError("Notify email is required.");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      await apiRequest(config, "/v1/user", {
        method: "POST",
        body: JSON.stringify({ notify_email: notifyEmail.trim() }),
      });
      window.location.replace("/ui/inputs");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="container py-6">
      <div className="mx-auto max-w-xl space-y-4">
        <Card className="animate-fade-in">
          <CardHeader>
            <CardTitle className="inline-flex items-center gap-2 text-2xl [font-family:var(--font-heading)]">
              <UserRoundPlus className="h-5 w-5 text-accent" />
              User Setup Required
            </CardTitle>
            <CardDescription>Create your user by binding a notify email before entering Inputs workspace.</CardDescription>
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
                {error ? (
                  <Alert>
                    <AlertTitle>Create user failed</AlertTitle>
                    <AlertDescription>{error}</AlertDescription>
                  </Alert>
                ) : null}
                <Button type="submit" disabled={busy}>
                  {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Create User
                </Button>
              </form>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function isUserNotInitializedError(error: unknown): boolean {
  if (!(error instanceof ApiError)) {
    return false;
  }
  if (error.status !== 404) {
    return false;
  }
  const body = error.body;
  if (!body || typeof body !== "object") {
    return false;
  }
  const detail = (body as Record<string, unknown>).detail;
  if (!detail || typeof detail !== "object") {
    return false;
  }
  return (detail as Record<string, unknown>).code === "user_not_initialized";
}
