import { redirect } from "next/navigation";
import OverviewPage from "@/components/overview-page-client";
import { requireServerSession } from "@/lib/server-auth";

export default async function DashboardPage() {
  const session = await requireServerSession();
  if (session.user.onboarding_stage !== "ready") {
    redirect("/onboarding");
  }
  return <OverviewPage />;
}
