import { LocalizedPageHeader } from "@/components/localized-page-header";
import { CanvasIcsSetupPanel } from "@/components/canvas-ics-setup-panel";
import { requireReadyServerSession } from "@/lib/server-auth";

export default async function CanvasIcsConnectPage() {
  await requireReadyServerSession();

  return (
    <div className="space-y-5">
      <LocalizedPageHeader
        eyebrowKey="pageHeader.sources"
        titleKey="sourceConnect.canvasTitle"
        descriptionKey="sourceConnect.canvasSummary"
      />
      <CanvasIcsSetupPanel />
    </div>
  );
}
