import { notFound } from "next/navigation";
import { SourceDetailPanel } from "@/components/source-detail-panel";

export default function PreviewSourceDetailPage({
  params,
}: {
  params: { sourceId: string };
}) {
  const sourceId = Number(params.sourceId);
  if (!Number.isInteger(sourceId) || sourceId <= 0) {
    notFound();
  }

  return <SourceDetailPanel sourceId={sourceId} basePath="/preview" />;
}
