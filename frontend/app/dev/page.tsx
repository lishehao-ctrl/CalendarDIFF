"use client";

import { FormEvent, useMemo, useState } from "react";
import { FlaskConical, Loader2 } from "lucide-react";

import { AppNav } from "@/components/dashboard/app-nav";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiRequest } from "@/lib/api";
import { getRuntimeConfig } from "@/lib/config";

export default function DevPage() {
  const config = useMemo(() => getRuntimeConfig(), []);
  const [subject, setSubject] = useState("[DEMO] CSE 151A Homework deadline moved");
  const [fromValue, setFromValue] = useState("instructor@example.edu");
  const [bodyText, setBodyText] = useState("Homework 2 deadline changed from Friday 5pm to Sunday 11:59pm.");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const enabled = Boolean(config.enableDevEndpoints && (config.appEnv ?? "").toLowerCase() === "dev");

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
    <div className="container py-4 md:py-6">
      <div className="mx-auto max-w-3xl space-y-4 md:space-y-6">
        <header className="animate-fade-in rounded-2xl border border-line bg-white/90 p-5 shadow-card">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="inline-flex items-center gap-2 text-2xl font-semibold [font-family:var(--font-heading)] md:text-3xl">
                <FlaskConical className="h-6 w-6 text-accent" />
                Dev Tools
              </h1>
              <p className="mt-1 text-sm text-muted">Inject one demo notify item from email-like text for UI verification.</p>
            </div>
            <AppNav current="dev" activeUserId={null} activeInputId={null} showDev={enabled} />
          </div>
        </header>

        {!enabled ? (
          <Alert>
            <AlertTitle>Dev endpoint disabled</AlertTitle>
            <AlertDescription>Set APP_ENV=dev and ENABLE_DEV_ENDPOINTS=true to use this page.</AlertDescription>
          </Alert>
        ) : (
          <Card>
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
      </div>
    </div>
  );
}
