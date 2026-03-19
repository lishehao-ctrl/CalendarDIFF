import { PageHeader } from "@/components/page-header";
import { ReviewChangesPanel } from "@/components/review-changes-panel";

export default function PreviewReviewChangesPage() {
  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Changes"
        title="Decision workspace"
        description="Open a change, review the evidence, then decide."
      />
      <ReviewChangesPanel basePath="/preview" />
    </div>
  );
}
