import dynamic from "next/dynamic";
import { LocalizedPageIntro } from "@/components/localized-page-intro";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";

const DeferredManualWorkbenchPanel = dynamic(
  () => import("@/components/manual-workbench-panel").then((mod) => mod.ManualWorkbenchPanel),
  {
    loading: () => <PanelLoadingPlaceholder rows={3} />,
  },
);

export default function PreviewManualPage() {
  return (
    <div className="space-y-4">
      <LocalizedPageIntro eyebrowKey="manual.heroEyebrow" titleKey="manual.heroTitle" />
      <DeferredManualWorkbenchPanel />
    </div>
  );
}
