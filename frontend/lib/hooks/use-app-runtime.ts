import { useCallback, useEffect, useState } from "react";

import { apiRequest, getOnboardingStatus } from "@/lib/api";
import { getRuntimeConfig } from "@/lib/config";
import { useToast } from "@/lib/hooks/use-toast";
import { isOnboardingRequiredError, toErrorMessage } from "@/lib/hooks/runtime-utils";
import { AppConfig, OnboardingStage } from "@/lib/types";

export function useAppRuntime() {
  const { toasts, pushToast } = useToast();

  const [config, setConfig] = useState<AppConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [needsOnboarding, setNeedsOnboarding] = useState(false);
  const [onboardingStage, setOnboardingStage] = useState<OnboardingStage | null>(null);

  useEffect(() => {
    const runtimeConfig = getRuntimeConfig();
    if (!runtimeConfig.apiKey) {
      setConfigError("Missing API key from /ui/app-config.js");
      return;
    }
    setConfig(runtimeConfig);
  }, []);

  const ensureOnboarded = useCallback(
    async (runtimeConfig?: AppConfig): Promise<boolean> => {
      const runtime = runtimeConfig ?? config;
      if (!runtime) {
        return false;
      }

      try {
        const onboarding = await getOnboardingStatus(runtime);
        setOnboardingStage(onboarding.stage);
        if (onboarding.stage !== "ready") {
          setNeedsOnboarding(true);
          return false;
        }

        await apiRequest<{
          id: number;
          email: string | null;
          notify_email: string | null;
          calendar_delay_seconds: number;
          created_at: string;
        }>(runtime, "/v1/user");
        setNeedsOnboarding(false);
        setConfigError(null);
        setOnboardingStage("ready");
        return true;
      } catch (error) {
        if (isOnboardingRequiredError(error)) {
          setNeedsOnboarding(true);
          setOnboardingStage(null);
          return false;
        }
        setConfigError(toErrorMessage(error));
        return false;
      }
    },
    [config]
  );

  return {
    config,
    configError,
    needsOnboarding,
    onboardingStage,
    isReady: onboardingStage === "ready",
    setNeedsOnboarding,
    ensureOnboarded,
    toasts,
    pushToast,
  };
}
