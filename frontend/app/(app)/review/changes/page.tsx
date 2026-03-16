import { PageHeader } from "@/components/page-header";
import { ReviewChangesPanel } from "@/components/review-changes-panel";
import { requireReadyServerSession } from "@/lib/server-auth";

export default async function ReviewChangesPage() {
  await requireReadyServerSession();
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Changes" title="Work the change inbox" description="Review proposed deadline updates, inspect evidence, and approve the timeline you want to keep." />
      <ReviewChangesPanel />
    </div>
  );
}
