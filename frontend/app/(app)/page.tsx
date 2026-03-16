import OverviewPage from "@/components/overview-page-client";
import { requireReadyServerSession } from "@/lib/server-auth";

export default async function DashboardPage() {
  await requireReadyServerSession();
  return <OverviewPage />;
}
