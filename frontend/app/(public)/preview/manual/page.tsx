import dynamic from "next/dynamic";
import { LocalizedPageIntro } from "@/components/localized-page-intro";
import { WorkbenchLoadingShell } from "@/components/workbench-loading-shell";

const DeferredManualWorkbenchPanel = dynamic(
  () => import("@/components/manual-workbench-panel").then((mod) => mod.ManualWorkbenchPanel),
  {
    loading: () => <WorkbenchLoadingShell variant="manual" />,
  },
);

export default function PreviewManualPage() {
  return (
    <div className="space-y-4">
      <LocalizedPageIntro eyebrowKey="manual.heroEyebrow" titleKey="manual.heroTitle" summaryKey="manual.heroSummary" />
      <DeferredManualWorkbenchPanel />
    </div>
  );
}
