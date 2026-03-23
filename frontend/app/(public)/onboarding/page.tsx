import { LocalizedPageIntro } from "@/components/localized-page-intro";
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
            <LocalizedPageIntro
              eyebrowKey="onboarding.introEyebrow"
              titleKey="onboarding.introTitle"
              summaryKey="onboarding.introSummary"
            />
          </div>
          <OnboardingWizard />
        </div>
      </div>
    </div>
  );
}
