import { PageHeader } from "@/components/page-header";
import { ReviewChangesPanel } from "@/components/review-changes-panel";

export default function ReviewChangesPage() {
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Changes" title="Work the change inbox" description="Review proposed deadline updates, inspect evidence, and approve the timeline you want to keep." />
      <ReviewChangesPanel />
    </div>
  );
}
