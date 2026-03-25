import dynamic from "next/dynamic";
import { LocalizedPageHeader } from "@/components/localized-page-header";
import { WorkbenchLoadingShell } from "@/components/workbench-loading-shell";
import { requireReadyServerSession } from "@/lib/server-auth";

const DeferredCanvasIcsSetupPanel = dynamic(
  () => import("@/components/canvas-ics-setup-panel").then((mod) => mod.CanvasIcsSetupPanel),
  {
    loading: () => <WorkbenchLoadingShell variant="source-connect" />,
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
