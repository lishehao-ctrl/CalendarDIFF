import { getServerSession } from "@/lib/server-auth";
import { redirect } from "next/navigation";
import { LoginPageClient } from "@/components/login-page-client";

export default async function LoginPage() {
  const session = await getServerSession();
  if (session) {
    redirect(session.user.onboarding_stage === "ready" ? "/" : "/onboarding");
  }
  return <LoginPageClient mode="login" />;
}
