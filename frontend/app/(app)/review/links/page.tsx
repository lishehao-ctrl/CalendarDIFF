import { PageHeader } from "@/components/page-header";
import { LinkReviewPanel } from "@/components/link-review-panel";

export default function ReviewLinksPage() {
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Links" title="Match and repair source links" description="Approve candidate matches, inspect current bindings, and fix bad pairings without leaving this workspace." />
      <LinkReviewPanel />
    </div>
  );
}
