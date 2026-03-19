import { notFound } from "next/navigation";
import { FamilyDetailPanel } from "@/components/family-management-panel";

export default function PreviewFamilyDetailPage({
  params,
}: {
  params: { familyId: string };
}) {
  const familyId = Number(params.familyId);
  if (!Number.isInteger(familyId) || familyId <= 0) {
    notFound();
  }

  return <FamilyDetailPanel familyId={familyId} basePath="/preview" />;
}
