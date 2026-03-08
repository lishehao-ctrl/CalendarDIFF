import { notFound } from "next/navigation";
import { PageHeader } from "@/components/page-header";
import { ReviewChangeEditPageClient } from "@/components/review-change-edit-page-client";

export default function ReviewChangeProposalEditPage({ params }: { params: { changeId: string } }) {
  const changeId = Number(params.changeId);
  if (!Number.isInteger(changeId) || changeId <= 0) {
    notFound();
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Review"
        title="Proposal Edit"
        description="Adjust a pending proposal before approving it into canonical state."
      />
      <ReviewChangeEditPageClient mode="proposal" changeId={changeId} />
    </div>
  );
}
