import dynamic from "next/dynamic";
import { LocalizedPageIntro } from "@/components/localized-page-intro";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";
import { requireReadyServerSession } from "@/lib/server-auth";

const DeferredManualWorkbenchPanel = dynamic(
  () => import("@/components/manual-workbench-panel").then((mod) => mod.ManualWorkbenchPanel),
  {
    loading: () => <PanelLoadingPlaceholder rows={3} />,
  },
);

export default async function ManualPage() {
  await requireReadyServerSession();

  return (
    <div className="space-y-4">
      <LocalizedPageIntro eyebrowKey="manual.heroEyebrow" titleKey="manual.heroTitle" summaryKey="manual.heroSummary" />
      <DeferredManualWorkbenchPanel />
    </div>
  );
}
