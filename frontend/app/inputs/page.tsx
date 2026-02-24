"use client";

import { useEffect } from "react";
import { CalendarDays } from "lucide-react";

import { AppNav } from "@/components/dashboard/app-nav";
import { InputSection } from "@/components/dashboard/sections/input-section";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { cn } from "@/lib/utils";
import { useDashboardData } from "@/lib/hooks/use-dashboard-data";

export default function InputsPage() {
  const {
    configError,
    showDevTools,
    toasts,
    needsOnboarding,
    activeSourceId,
    sourceUrl,
    sourceTermId,
    sourceEmailLabel,
    sourceEmailFromContains,
    sourceEmailSubjectKeywords,
    setSourceUrl,
    setSourceTermId,
    setSourceEmailLabel,
    setSourceEmailFromContains,
    setSourceEmailSubjectKeywords,
    createBusy,
    activeUserTerms,
    handleCreateCalendarInput,
    handleConnectGmailInput,
  } = useDashboardData();

  useEffect(() => {
    if (!needsOnboarding) {
      return;
    }
    window.location.replace("/ui/onboarding");
  }, [needsOnboarding]);

  return (
    <div className="container py-4 md:py-6">
      <div className="mx-auto max-w-6xl space-y-4 md:space-y-6">
        <header className="animate-fade-in rounded-2xl border border-line bg-white/90 p-5 shadow-card">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="inline-flex items-center gap-2 text-2xl font-semibold [font-family:var(--font-heading)] md:text-3xl">
                <CalendarDays className="h-6 w-6 text-accent" />
                Inputs
              </h1>
              <p className="mt-1 text-sm text-muted">
                Add calendar and Gmail sources. Processing, feed, and runs are managed in their own workspaces.
              </p>
            </div>
            <AppNav current="inputs" activeInputId={activeSourceId} showDev={showDevTools} />
          </div>
        </header>

        {configError ? (
          <Alert>
            <AlertTitle>Configuration Missing</AlertTitle>
            <AlertDescription>{configError}</AlertDescription>
          </Alert>
        ) : null}

        <InputSection
          sourceUrl={sourceUrl}
          sourceTermId={sourceTermId}
          sourceEmailLabel={sourceEmailLabel}
          sourceEmailFromContains={sourceEmailFromContains}
          sourceEmailSubjectKeywords={sourceEmailSubjectKeywords}
          activeUserTerms={activeUserTerms}
          createBusy={createBusy}
          onSourceUrlChange={setSourceUrl}
          onSourceTermIdChange={setSourceTermId}
          onSourceEmailLabelChange={setSourceEmailLabel}
          onSourceEmailFromContainsChange={setSourceEmailFromContains}
          onSourceEmailSubjectKeywordsChange={setSourceEmailSubjectKeywords}
          onCreateCalendarInput={handleCreateCalendarInput}
          onConnectGmailInput={handleConnectGmailInput}
        />
      </div>

      <div className="fixed bottom-4 right-4 z-50 space-y-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={cn(
              "max-w-[420px] rounded-xl px-4 py-3 text-sm text-white shadow-xl",
              toast.tone === "success" && "bg-emerald-700",
              toast.tone === "error" && "bg-rose-700",
              toast.tone === "info" && "bg-slate-800"
            )}
          >
            {toast.message}
          </div>
        ))}
      </div>
    </div>
  );
}
