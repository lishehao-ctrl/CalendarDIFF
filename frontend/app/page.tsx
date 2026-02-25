"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { getOnboardingStatus } from "@/lib/api";
import { getRuntimeConfig } from "@/lib/config";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function UiRootRedirectPage() {
  const [message, setMessage] = useState("Checking user setup...");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const runtimeConfig = getRuntimeConfig();
    if (!runtimeConfig.apiKey) {
      setError("Missing API key from /ui/app-config.js");
      return;
    }

    void (async () => {
      try {
        const status = await getOnboardingStatus(runtimeConfig);
        if (status.stage !== "ready") {
          const target = new URL("/ui/onboarding", window.location.origin);
          window.location.replace(target.pathname);
          return;
        }
        const target = new URL("/ui/processing", window.location.origin);
        target.search = window.location.search;
        target.hash = window.location.hash;
        window.location.replace(`${target.pathname}${target.search}${target.hash}`);
      } catch (err) {
        const detail = err instanceof Error ? err.message : String(err);
        setMessage("Failed to resolve entry route.");
        setError(detail);
      }
    })();
  }, []);

  return (
    <div className="container py-6">
      <div className="mx-auto max-w-xl">
        <Card>
          <CardHeader>
            <CardTitle>Redirecting</CardTitle>
            <CardDescription>{message}</CardDescription>
          </CardHeader>
          <CardContent>
            {error ? (
              <div className="text-sm text-rose-700">{error}</div>
            ) : (
              <div className="flex items-center text-sm text-muted">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Please wait.
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
