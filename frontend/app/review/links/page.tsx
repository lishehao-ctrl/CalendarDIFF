import { PageHeader } from "@/components/page-header";
import { LinkReviewPanel } from "@/components/link-review-panel";

export default function ReviewLinksPage() {
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Linking" title="Link Review Workspace" description="Moderate candidates, inspect auto-links, and clear link-risk alerts from one dedicated workspace." />
      <LinkReviewPanel />
    </div>
  );
}
