import { getServerSession } from "@/lib/server-auth";
import { redirect } from "next/navigation";
import { LoginPageClient } from "@/components/login-page-client";

export default async function RegisterPage() {
  const session = await getServerSession();
  if (session) {
    redirect("/");
  }
  return <LoginPageClient mode="register" />;
}
