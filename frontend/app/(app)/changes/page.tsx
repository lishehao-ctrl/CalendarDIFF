import { ChangeItemsPanel } from "@/components/review-changes-panel";
import { requireReadyServerSession } from "@/lib/server-auth";

export default async function ChangesPage({
  searchParams,
}: {
  searchParams?: Promise<{ bucket?: string }>;
}) {
  await requireReadyServerSession();
  const params = (await searchParams) ?? {};
  const reviewBucket = params.bucket === "initial_review" ? "initial_review" : "changes";
  return <ChangeItemsPanel reviewBucket={reviewBucket} />;
}
