import dynamic from "next/dynamic";
import { notFound } from "next/navigation";
import { LocalizedPageIntro } from "@/components/localized-page-intro";
import { WorkbenchLoadingShell } from "@/components/workbench-loading-shell";
import { requireReadyServerSession } from "@/lib/server-auth";

const DeferredSourceDetailPanel = dynamic(
  () => import("@/components/source-detail-panel").then((mod) => mod.SourceDetailPanel),
  {
    loading: () => <WorkbenchLoadingShell variant="source-detail" />,
  },
);

export default async function SourceDetailPage({
  params,
}: {
  params: { sourceId: string };
}) {
  await requireReadyServerSession();
  const sourceId = Number(params.sourceId);
  if (!Number.isInteger(sourceId) || sourceId <= 0) {
    notFound();
  }

  return (
    <div className="space-y-4">
      <LocalizedPageIntro eyebrowKey="sources.detail.pageEyebrow" titleKey="sources.heroTitle" summaryKey="sources.heroSummary" />
      <DeferredSourceDetailPanel sourceId={sourceId} />
    </div>
  );
}
