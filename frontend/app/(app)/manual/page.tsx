import dynamic from "next/dynamic";
import { LocalizedPageIntro } from "@/components/localized-page-intro";
import { WorkbenchLoadingShell } from "@/components/workbench-loading-shell";
import { requireReadyServerSession } from "@/lib/server-auth";

const DeferredManualWorkbenchPanel = dynamic(
  () => import("@/components/manual-workbench-panel").then((mod) => mod.ManualWorkbenchPanel),
  {
    loading: () => <WorkbenchLoadingShell variant="manual" />,
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
