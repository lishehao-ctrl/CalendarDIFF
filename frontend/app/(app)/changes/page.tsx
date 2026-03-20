import { ChangeItemsPanel } from "@/components/review-changes-panel";
import { requireReadyServerSession } from "@/lib/server-auth";

export default async function ChangesPage() {
  await requireReadyServerSession();
  return <ChangeItemsPanel />;
}
