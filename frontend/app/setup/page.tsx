import { redirect } from "next/navigation";
import { requireServerSession } from "@/lib/server-auth";

export default async function SetupPage() {
  await requireServerSession();
  redirect("/onboarding");
}
