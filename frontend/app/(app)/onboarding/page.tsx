import { redirect } from "next/navigation";
import { requireServerSession } from "@/lib/server-auth";

export default async function OnboardingPage() {
  await requireServerSession();
  redirect("/setup");
}
