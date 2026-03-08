import { notFound } from "next/navigation";
import { PageHeader } from "@/components/page-header";
import { ReviewChangeEditPageClient } from "@/components/review-change-edit-page-client";

export default function ReviewChangeCanonicalEditPage({ params }: { params: { changeId: string } }) {
  const changeId = Number(params.changeId);
  if (!Number.isInteger(changeId) || changeId <= 0) {
    notFound();
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Review"
        title="Canonical Edit"
        description="Apply a direct canonical correction for this review item using the unified edit flow."
      />
      <ReviewChangeEditPageClient mode="canonical" changeId={changeId} />
    </div>
  );
}
