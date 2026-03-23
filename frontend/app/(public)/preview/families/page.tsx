import dynamic from "next/dynamic";
import { LocalizedPageIntro } from "@/components/localized-page-intro";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";
import { translate } from "@/lib/i18n/runtime";

const DeferredFamilyManagementPanel = dynamic(
  () => import("@/components/family-management-panel").then((mod) => mod.FamilyManagementPanel),
  {
    loading: () => (
      <PanelLoadingPlaceholder
        eyebrow={translate("families.heroEyebrow")}
        title={translate("families.heroTitle")}
        summary={translate("families.heroSummary")}
        rows={3}
      />
    ),
  },
);

export default function PreviewFamilyManagePage() {
  return (
    <div className="space-y-4">
      <LocalizedPageIntro eyebrowKey="families.heroEyebrow" titleKey="families.heroTitle" summaryKey="families.heroSummary" />
      <DeferredFamilyManagementPanel basePath="/preview" />
    </div>
  );
}
