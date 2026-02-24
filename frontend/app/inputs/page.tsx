"use client";

import { useEffect } from "react";
import { CalendarDays } from "lucide-react";

import { DashboardPage, DashboardPageHeader } from "@/components/dashboard/page-shell";
import { InputSection } from "@/components/dashboard/sections/input-section";
import { DashboardToastStack } from "@/components/dashboard/toast-stack";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
    <DashboardPage>
      <DashboardPageHeader
        icon={CalendarDays}
        title="Inputs"
        description="Add calendar and Gmail sources. Processing, feed, and runs are managed in their own workspaces."
        current="inputs"
        activeInputId={activeSourceId}
        showDev={showDevTools}
      />

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

      <DashboardToastStack toasts={toasts} />
    </DashboardPage>
  );
}
