import dynamic from "next/dynamic";
import { LocalizedPageHeader } from "@/components/localized-page-header";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";
import { requireReadyServerSession } from "@/lib/server-auth";

const DeferredCanvasIcsSetupPanel = dynamic(
  () => import("@/components/canvas-ics-setup-panel").then((mod) => mod.CanvasIcsSetupPanel),
  {
    loading: () => <PanelLoadingPlaceholder rows={2} />,
  },
);

export default async function CanvasIcsConnectPage() {
  await requireReadyServerSession();

  return (
    <div className="space-y-5">
      <LocalizedPageHeader
        eyebrowKey="pageHeader.sources"
        titleKey="sourceConnect.canvasTitle"
        descriptionKey="sourceConnect.canvasSummary"
      />
      <DeferredCanvasIcsSetupPanel />
    </div>
  );
}
