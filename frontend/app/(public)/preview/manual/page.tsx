import { LocalizedPageIntro } from "@/components/localized-page-intro";
import { ManualWorkbenchPanel } from "@/components/manual-workbench-panel";

export default function PreviewManualPage() {
  return (
    <div className="space-y-4">
      <LocalizedPageIntro eyebrowKey="manual.heroEyebrow" titleKey="manual.heroTitle" />
      <ManualWorkbenchPanel />
    </div>
  );
}
