"use client";

import { useEffect } from "react";
import { BellRing } from "lucide-react";

import { DashboardPage, DashboardPageHeader } from "@/components/dashboard/page-shell";
import { DiffSection } from "@/components/dashboard/sections/diff-section";
import { DashboardToastStack } from "@/components/dashboard/toast-stack";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useDashboardData } from "@/lib/hooks/use-dashboard-data";

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
    feedTermScope,
    setFeedTermScope,
    feedTermId,
    setFeedTermId,
    activeUserTerms,
    filteredChanges,
    changesLoading,
    changesError,
    handleRefreshChanges,
    handleToggleViewed,
    handleDownloadEvidence,
    changeNotes,
    setChangeNote,
    getTaskDisplayTitle,
    getCourseDisplayLabel,
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
        icon={BellRing}
        title="Feed"
        description="Review aggregated changes across email and calendar inputs with term filters."
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
        feedTermScope={feedTermScope}
        onFeedTermScopeChange={setFeedTermScope}
        feedTermId={feedTermId}
        onFeedTermIdChange={setFeedTermId}
        activeUserTerms={activeUserTerms}
        changesError={changesError}
        changesLoading={changesLoading}
        filteredChanges={filteredChanges}
        changeNotes={changeNotes}
        onChangeNote={setChangeNote}
        onToggleViewed={handleToggleViewed}
        onDownloadEvidence={handleDownloadEvidence}
        onRefreshChanges={handleRefreshChanges}
        getTaskDisplayTitle={getTaskDisplayTitle}
        getCourseDisplayLabel={getCourseDisplayLabel}
      />

      <DashboardToastStack toasts={toasts} />
    </DashboardPage>
  );
}
