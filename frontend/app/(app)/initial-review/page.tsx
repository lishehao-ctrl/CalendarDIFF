import { InitialReviewPanel } from "@/components/initial-review-panel";
import { requireReadyServerSession } from "@/lib/server-auth";

export default async function InitialReviewPage() {
  await requireReadyServerSession();
  return <InitialReviewPanel />;
}
