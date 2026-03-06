import { PageHeader } from "@/components/page-header";
import { SourcesPanel } from "@/components/sources-panel";

export default function SourcesPage() {
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Control Plane" title="Sources & Sync" description="Connect ICS feeds, inspect source health, and trigger manual syncs without leaving the console." />
      <SourcesPanel />
    </div>
  );
}
