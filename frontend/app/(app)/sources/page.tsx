import { SourcesPanel } from "@/components/sources-panel";
import { requireReadyServerSession } from "@/lib/server-auth";

export default async function SourcesPage() {
  await requireReadyServerSession();
  return (
    <div className="space-y-5">
      <SourcesPanel />
    </div>
  );
}
