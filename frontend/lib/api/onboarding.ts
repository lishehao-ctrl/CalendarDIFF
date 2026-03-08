import { apiGet } from "@/lib/api/client";
import type { OnboardingStatus } from "@/lib/types";

export async function getOnboardingStatus() {
  return apiGet<OnboardingStatus>("/onboarding/status");
}
