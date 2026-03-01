import { apiRequest } from "@/lib/api/client";
import { AppConfig, OnboardingRegisterRequest, OnboardingRegisterResponse, OnboardingStatus } from "@/lib/types";

export function getOnboardingStatus(config: AppConfig): Promise<OnboardingStatus> {
  return apiRequest<OnboardingStatus>(config, "/v2/onboarding/status");
}

export function registerOnboarding(
  config: AppConfig,
  payload: OnboardingRegisterRequest
): Promise<OnboardingRegisterResponse> {
  return apiRequest<OnboardingRegisterResponse>(config, "/v2/onboarding/registrations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
