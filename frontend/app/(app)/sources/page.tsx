import { PageHeader } from "@/components/page-header";
import { SourcesPanel } from "@/components/sources-panel";

export default function SourcesPage() {
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Sources" title="Connect and maintain intake" description="Manage your Canvas and Gmail sources, watch sync health, and trigger refreshes when you need them." />
      <SourcesPanel />
    </div>
  );
}
