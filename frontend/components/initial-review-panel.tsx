"use client";

import { ChangeItemsPanel } from "@/components/review-changes-panel";

export function InitialReviewPanel({ basePath = "" }: { basePath?: string }) {
  return <ChangeItemsPanel basePath={basePath} lane="initial_review" />;
}
