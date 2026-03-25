import dynamic from "next/dynamic";
import { LocalizedPageIntro } from "@/components/localized-page-intro";
import { WorkbenchLoadingShell } from "@/components/workbench-loading-shell";

const DeferredFamilyManagementPanel = dynamic(
  () => import("@/components/family-management-panel").then((mod) => mod.FamilyManagementPanel),
  {
    loading: () => <WorkbenchLoadingShell variant="families" />,
  },
);

export default function FamilyManagePage() {
  return (
    <div className="space-y-4">
      <LocalizedPageIntro eyebrowKey="families.heroEyebrow" titleKey="families.heroTitle" summaryKey="families.heroSummary" />
      <DeferredFamilyManagementPanel />
    </div>
  );
}
