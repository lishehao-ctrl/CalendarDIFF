"use client";

import { useEffect } from "react";
import { BellRing } from "lucide-react";

import { DashboardPage, DashboardPageHeader } from "@/components/dashboard/page-shell";
import { DiffSection } from "@/components/dashboard/sections/diff-section";
import { DashboardToastStack } from "@/components/dashboard/toast-stack";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useFeedData } from "@/lib/hooks/use-feed-data";

export default function FeedPage() {
  const {
    configError,
    toasts,
    needsOnboarding,
    activeSourceId,
    changeFilter,
    setChangeFilter,
    changeSourceTypeFilter,
    setChangeSourceTypeFilter,
    filteredChanges,
    changesLoading,
    changesError,
    handleRefreshChanges,
    handleToggleViewed,
    changeNotes,
    setChangeNote,
  } = useFeedData();

  useEffect(() => {
    if (!needsOnboarding) {
      return;
    }
    window.location.replace("/ui/onboarding");
  }, [needsOnboarding]);

  return (
    <DashboardPage>
      <DashboardPageHeader
        icon={BellRing}
        title="Feed"
        description="Review aggregated changes across email and calendar inputs."
        current="feed"
        activeInputId={activeSourceId}
        showOnboardingNav={needsOnboarding}
      />

      {configError ? (
        <Alert>
          <AlertTitle>Configuration Missing</AlertTitle>
          <AlertDescription>{configError}</AlertDescription>
        </Alert>
      ) : null}

      <DiffSection
        changeFilter={changeFilter}
        onChangeFilter={setChangeFilter}
        changeSourceTypeFilter={changeSourceTypeFilter}
        onChangeSourceTypeFilter={setChangeSourceTypeFilter}
        changesError={changesError}
        changesLoading={changesLoading}
        filteredChanges={filteredChanges}
        changeNotes={changeNotes}
        onChangeNote={setChangeNote}
        onToggleViewed={handleToggleViewed}
        onRefreshChanges={handleRefreshChanges}
      />

      <DashboardToastStack toasts={toasts} />
    </DashboardPage>
  );
}
