import { PageHeader } from "@/components/page-header";
import { ReviewChangesPanel } from "@/components/review-changes-panel";

export default function ReviewChangesPage() {
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Review" title="Review Inbox" description="Triage canonical changes with evidence-backed decisions and keep the event timeline clean." />
      <ReviewChangesPanel />
    </div>
  );
}
