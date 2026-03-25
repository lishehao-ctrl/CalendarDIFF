import dynamic from "next/dynamic";
import { notFound } from "next/navigation";
import { LocalizedPageIntro } from "@/components/localized-page-intro";
import { WorkbenchLoadingShell } from "@/components/workbench-loading-shell";

const DeferredSourceDetailPanel = dynamic(
  () => import("@/components/source-detail-panel").then((mod) => mod.SourceDetailPanel),
  {
    loading: () => <WorkbenchLoadingShell variant="source-detail" />,
  },
);

export default function PreviewSourceDetailPage({
  params,
}: {
  params: { sourceId: string };
}) {
  const sourceId = Number(params.sourceId);
  if (!Number.isInteger(sourceId) || sourceId <= 0) {
    notFound();
  }

  return (
    <div className="space-y-4">
      <LocalizedPageIntro eyebrowKey="sources.detail.pageEyebrow" titleKey="sources.heroTitle" summaryKey="sources.heroSummary" />
      <DeferredSourceDetailPanel sourceId={sourceId} basePath="/preview" />
    </div>
  );
}
