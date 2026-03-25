import { ChangeItemsPanel } from "@/components/review-changes-panel";

export default async function PreviewChangesPage({
  searchParams,
}: {
  searchParams?: Promise<{ bucket?: string }>;
}) {
  const params = (await searchParams) ?? {};
  const reviewBucket = params.bucket === "initial_review" ? "initial_review" : "changes";
  return <ChangeItemsPanel basePath="/preview" reviewBucket={reviewBucket} />;
}
