import { PageHeader } from "@/components/page-header";
import { CanvasIcsSetupPanel } from "@/components/canvas-ics-setup-panel";
import { requireReadyServerSession } from "@/lib/server-auth";

export default async function CanvasIcsConnectPage() {
  await requireReadyServerSession();

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Sources"
        title="Canvas ICS Setup"
        description="Connect or update the single Canvas ICS subscription used by this workspace."
      />
      <CanvasIcsSetupPanel />
    </div>
  );
}
