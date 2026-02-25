"use client";

import { useEffect } from "react";
import { CalendarDays } from "lucide-react";

import { DashboardPage, DashboardPageHeader } from "@/components/dashboard/page-shell";
import { InputSection } from "@/components/dashboard/sections/input-section";
import { DashboardToastStack } from "@/components/dashboard/toast-stack";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useInputsData } from "@/lib/hooks/use-inputs-data";

export default function InputsPage() {
  const {
    configError,
    showDevTools,
    toasts,
    needsOnboarding,
    activeSourceId,
    sourceEmailLabel,
    sourceEmailFromContains,
    sourceEmailSubjectKeywords,
    setSourceEmailLabel,
    setSourceEmailFromContains,
    setSourceEmailSubjectKeywords,
    createBusy,
    handleConnectGmailInput,
  } = useInputsData();

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
        description="Manage Gmail sources. ICS baseline is configured in onboarding."
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
        sourceEmailLabel={sourceEmailLabel}
        sourceEmailFromContains={sourceEmailFromContains}
        sourceEmailSubjectKeywords={sourceEmailSubjectKeywords}
        createBusy={createBusy}
        onSourceEmailLabelChange={setSourceEmailLabel}
        onSourceEmailFromContainsChange={setSourceEmailFromContains}
        onSourceEmailSubjectKeywordsChange={setSourceEmailSubjectKeywords}
        onConnectGmailInput={handleConnectGmailInput}
      />

      <DashboardToastStack toasts={toasts} />
    </DashboardPage>
  );
}
