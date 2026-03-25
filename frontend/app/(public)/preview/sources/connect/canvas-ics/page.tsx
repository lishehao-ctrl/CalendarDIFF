import dynamic from "next/dynamic";
import { WorkbenchLoadingShell } from "@/components/workbench-loading-shell";

const DeferredCanvasIcsSetupPanel = dynamic(
  () => import("@/components/canvas-ics-setup-panel").then((mod) => mod.CanvasIcsSetupPanel),
  {
    loading: () => <WorkbenchLoadingShell variant="source-connect" />,
  },
);

export default function PreviewCanvasIcsPage() {
  return <DeferredCanvasIcsSetupPanel basePath="/preview" />;
}
