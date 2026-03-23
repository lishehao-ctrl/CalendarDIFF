import { notFound } from "next/navigation";
import { LocalizedPageHeader } from "@/components/localized-page-header";
import { ChangeItemEditPageClient } from "@/components/review-change-edit-page-client";
import type { ChangeEditMode } from "@/lib/types";

function parseMode(rawMode: string): ChangeEditMode | null {
  if (rawMode === "canonical" || rawMode === "proposal") {
    return rawMode;
  }
  return null;
}

export default function PreviewChangeEditModePage({
  params,
}: {
  params: { changeId: string; mode: string };
}) {
  const changeId = Number(params.changeId);
  const mode = parseMode(params.mode);
  if (!Number.isInteger(changeId) || changeId <= 0 || mode === null) {
    notFound();
  }

  return (
    <div className="space-y-5">
      <LocalizedPageHeader
        eyebrowKey="pageHeader.preview"
        titleKey={mode === "canonical" ? "changeEdit.directEdit" : "changeEdit.proposalEdit"}
        descriptionKey={mode === "canonical" ? "changeEdit.previewDirectEditSummary" : "changeEdit.previewProposalEditSummary"}
      />
      <ChangeItemEditPageClient mode={mode} changeId={changeId} basePath="/preview" />
    </div>
  );
}
