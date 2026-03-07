import Link from "next/link";
import { redirect } from "next/navigation";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { requireServerSession } from "@/lib/server-auth";

export default async function OnboardingPage() {
  const session = await requireServerSession();
  if (session.user.onboarding_stage === "ready") {
    redirect("/");
  }

  return (
    <div className="space-y-5">
      <Card className="max-w-3xl p-8">
        <p className="text-xs uppercase tracking-[0.24em] text-[#6d7885]">Onboarding</p>
        <h1 className="mt-3 text-3xl font-semibold">Connect your first source</h1>
        <p className="mt-4 text-sm leading-7 text-[#596270]">
          Your account is active, but the workspace has no active source yet. Start by connecting an ICS feed or Gmail so review and linking work can begin.
        </p>
        <div className="mt-6 flex gap-3">
          <Link href="/sources"><Button>Open Sources</Button></Link>
        </div>
      </Card>
    </div>
  );
}
