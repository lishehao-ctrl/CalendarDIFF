import { notFound } from "next/navigation";
import { SourceDetailPanel } from "@/components/source-detail-panel";
import { requireReadyServerSession } from "@/lib/server-auth";

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

  return <SourceDetailPanel sourceId={sourceId} />;
}
