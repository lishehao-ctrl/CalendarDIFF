import { redirect } from "next/navigation";
import { OnboardingWizard } from "@/components/onboarding-wizard";
import { requireServerSession } from "@/lib/server-auth";

export default async function OnboardingPage() {
  const session = await requireServerSession();
  if (session.user.onboarding_stage === "ready") {
    redirect("/");
  }

  return (
    <div className="min-h-screen px-4 py-8 md:px-8">
      <div className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-6xl items-center justify-center">
        <div className="w-full">
          <div className="mb-6 max-w-3xl">
            <p className="text-xs uppercase tracking-[0.24em] text-[#6d7885]">Onboarding</p>
            <h1 className="mt-3 text-4xl font-semibold leading-tight text-ink md:text-5xl">
              Connect sources and define the term before the workspace opens.
            </h1>
            <p className="mt-4 max-w-2xl text-sm leading-7 text-[#596270]">
              This flow stays separate from the main workspace on purpose. Finish Canvas, choose whether Gmail joins,
              and save the term window once. After that, Overview becomes your default entry point.
            </p>
          </div>
          <OnboardingWizard />
        </div>
      </div>
    </div>
  );
}
