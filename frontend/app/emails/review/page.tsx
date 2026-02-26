"use client";

import { useEffect } from "react";
import { BellRing } from "lucide-react";

import { DashboardPage, DashboardPageHeader } from "@/components/dashboard/page-shell";
import { EmailReviewSection } from "@/components/dashboard/sections/email-review-section";
import { DashboardToastStack } from "@/components/dashboard/toast-stack";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useEmailReviewQueue } from "@/lib/hooks/use-email-review-queue";

export default function EmailReviewPage() {
  const {
    toasts,
    configError,
    needsOnboarding,
    items,
    loading,
    refreshing,
    error,
    busyEmailId,
    lastAppliedChangeId,
    applyDrafts,
    loadQueue,
    handleApply,
    handleRoute,
    handleMarkViewed,
    updateApplyDraft,
  } = useEmailReviewQueue();

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
        title="Email Review"
        description="Review rule-derived email candidates before applying them into your canonical timeline."
        current="emails"
        activeInputId={null}
        actions={
          <Button variant="secondary" asChild>
            <a href="/ui/feed">Open Feed</a>
          </Button>
        }
      />

      {configError ? (
        <Alert>
          <AlertTitle>Configuration Missing</AlertTitle>
          <AlertDescription>{configError}</AlertDescription>
        </Alert>
      ) : null}

      {lastAppliedChangeId !== null ? (
        <Alert>
          <AlertTitle>Applied Successfully</AlertTitle>
          <AlertDescription>
            Latest applied change: #{lastAppliedChangeId}. Open Feed to inspect the created record.
          </AlertDescription>
        </Alert>
      ) : null}

      <EmailReviewSection
        items={items}
        loading={loading}
        refreshing={refreshing}
        error={error}
        busyEmailId={busyEmailId}
        applyDrafts={applyDrafts}
        onRefresh={loadQueue}
        onApply={handleApply}
        onRoute={handleRoute}
        onMarkViewed={handleMarkViewed}
        onUpdateApplyDraft={updateApplyDraft}
      />

      <DashboardToastStack toasts={toasts} />
    </DashboardPage>
  );
}
