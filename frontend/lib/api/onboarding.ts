import { apiRequest } from "@/lib/api/client";
import { AppConfig, OnboardingRegisterRequest, OnboardingRegisterResponse, OnboardingStatus } from "@/lib/types";

export function getOnboardingStatus(config: AppConfig): Promise<OnboardingStatus> {
  return apiRequest<OnboardingStatus>(config, "/v1/onboarding/status");
}

export function registerOnboarding(
  config: AppConfig,
  payload: OnboardingRegisterRequest
): Promise<OnboardingRegisterResponse> {
  return apiRequest<OnboardingRegisterResponse>(config, "/v1/onboarding/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
