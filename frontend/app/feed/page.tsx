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
    showDevTools,
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
    evidencePreviews,
    handlePreviewEvidence,
    changeNotes,
    setChangeNote,
    getTaskDisplayTitle,
    getCourseDisplayLabel,
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
        showDev={showDevTools}
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
        evidencePreviews={evidencePreviews}
        onPreviewEvidence={handlePreviewEvidence}
        onRefreshChanges={handleRefreshChanges}
        getTaskDisplayTitle={getTaskDisplayTitle}
        getCourseDisplayLabel={getCourseDisplayLabel}
      />

      <DashboardToastStack toasts={toasts} />
    </DashboardPage>
  );
}
