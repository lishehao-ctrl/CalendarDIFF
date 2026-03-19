import { notFound } from "next/navigation";
import { PageHeader } from "@/components/page-header";
import { ReviewChangeEditPageClient } from "@/components/review-change-edit-page-client";
import type { ReviewEditMode } from "@/lib/types";

const EDIT_MODE_COPY: Record<ReviewEditMode, { title: string; description: string }> = {
  canonical: {
    title: "Direct Edit",
    description: "Update the current approved event in preview mode.",
  },
  proposal: {
    title: "Proposal Edit",
    description: "Adjust a pending proposal in preview mode.",
  },
};

function parseMode(rawMode: string): ReviewEditMode | null {
  if (rawMode === "canonical" || rawMode === "proposal") {
    return rawMode;
  }
  return null;
}

export default function PreviewReviewChangeEditModePage({
  params,
}: {
  params: { changeId: string; mode: string };
}) {
  const changeId = Number(params.changeId);
  const mode = parseMode(params.mode);
  if (!Number.isInteger(changeId) || changeId <= 0 || mode === null) {
    notFound();
  }

  const copy = EDIT_MODE_COPY[mode];

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Preview" title={copy.title} description={copy.description} />
      <ReviewChangeEditPageClient mode={mode} changeId={changeId} basePath="/preview" />
    </div>
  );
}
