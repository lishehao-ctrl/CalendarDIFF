import { PageHeader } from "@/components/page-header";
import { CanvasIcsSetupPanel } from "@/components/canvas-ics-setup-panel";

export default function CanvasIcsConnectPage() {
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
