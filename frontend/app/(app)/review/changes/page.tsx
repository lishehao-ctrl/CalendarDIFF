import { PageHeader } from "@/components/page-header";
import { ReviewChangesPanel } from "@/components/review-changes-panel";
import { requireReadyServerSession } from "@/lib/server-auth";

export default async function ReviewChangesPage() {
  await requireReadyServerSession();
  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Changes"
        title="Decision workspace"
        description="Open a change, review the evidence, then decide."
      />
      <ReviewChangesPanel />
    </div>
  );
}
