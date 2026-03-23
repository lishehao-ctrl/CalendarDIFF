import dynamic from "next/dynamic";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";

const DeferredCanvasIcsSetupPanel = dynamic(
  () => import("@/components/canvas-ics-setup-panel").then((mod) => mod.CanvasIcsSetupPanel),
  {
    loading: () => <PanelLoadingPlaceholder rows={2} />,
  },
);

export default function PreviewCanvasIcsPage() {
  return <DeferredCanvasIcsSetupPanel basePath="/preview" />;
}
