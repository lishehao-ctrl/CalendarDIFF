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
    loadQueue,
    handleRoute,
    handleMarkViewed,
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
        description="Review rule-derived email candidates and keep queue state clean with route and viewed actions."
        current="emails"
        activeInputId={null}
        showOnboardingNav={needsOnboarding}
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

      <EmailReviewSection
        items={items}
        loading={loading}
        refreshing={refreshing}
        error={error}
        busyEmailId={busyEmailId}
        onRefresh={loadQueue}
        onRoute={handleRoute}
        onMarkViewed={handleMarkViewed}
      />

      <DashboardToastStack toasts={toasts} />
    </DashboardPage>
  );
}
