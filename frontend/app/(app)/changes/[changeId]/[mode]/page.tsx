import { notFound } from "next/navigation";
import { PageHeader } from "@/components/page-header";
import { ChangeItemEditPageClient } from "@/components/review-change-edit-page-client";
import { requireReadyServerSession } from "@/lib/server-auth";
import type { ChangeEditMode } from "@/lib/types";

const EDIT_MODE_COPY: Record<ChangeEditMode, { title: string; description: string }> = {
  canonical: {
    title: "Direct Edit",
    description: "Update the current approved event before returning to Changes.",
  },
  proposal: {
    title: "Proposal Edit",
    description: "Adjust a pending proposal before approving it into canonical state.",
  },
};

function parseMode(rawMode: string): ChangeEditMode | null {
  if (rawMode === "canonical" || rawMode === "proposal") {
    return rawMode;
  }
  return null;
}

export default async function ChangeEditModePage({
  params,
}: {
  params: { changeId: string; mode: string };
}) {
  await requireReadyServerSession();
  const changeId = Number(params.changeId);
  const mode = parseMode(params.mode);
  if (!Number.isInteger(changeId) || changeId <= 0 || mode === null) {
    notFound();
  }

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Changes" title={EDIT_MODE_COPY[mode].title} description={EDIT_MODE_COPY[mode].description} />
      <ChangeItemEditPageClient mode={mode} changeId={changeId} />
    </div>
  );
}
