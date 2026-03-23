import { LocalizedPageIntro } from "@/components/localized-page-intro";
import { ManualWorkbenchPanel } from "@/components/manual-workbench-panel";
import { requireReadyServerSession } from "@/lib/server-auth";

export default async function ManualPage() {
  await requireReadyServerSession();

  return (
    <div className="space-y-4">
      <LocalizedPageIntro eyebrowKey="manual.heroEyebrow" titleKey="manual.heroTitle" summaryKey="manual.heroSummary" />
      <ManualWorkbenchPanel />
    </div>
  );
}
