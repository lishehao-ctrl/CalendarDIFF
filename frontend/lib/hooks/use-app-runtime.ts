import { useCallback, useEffect, useState } from "react";

import { getWorkspaceBootstrap } from "@/lib/api";
import { getRuntimeConfig } from "@/lib/config";
import { useToast } from "@/lib/hooks/use-toast";
import { toErrorMessage } from "@/lib/hooks/runtime-utils";
import { AppConfig, OnboardingStage, WorkspaceBootstrapResponse } from "@/lib/types";

export function useAppRuntime() {
  const { toasts, pushToast } = useToast();

  const [config, setConfig] = useState<AppConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [needsOnboarding, setNeedsOnboarding] = useState(false);
  const [onboardingStage, setOnboardingStage] = useState<OnboardingStage | null>(null);
  const [bootstrap, setBootstrap] = useState<WorkspaceBootstrapResponse | null>(null);

  useEffect(() => {
    const runtimeConfig = getRuntimeConfig();
    if (!runtimeConfig.apiKey) {
      setConfigError("Missing API key from /ui/app-config.js");
      return;
    }
    setConfig(runtimeConfig);
    void loadBootstrap(runtimeConfig);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadBootstrap = useCallback(
    async (runtimeConfig?: AppConfig): Promise<WorkspaceBootstrapResponse | null> => {
      const runtime = runtimeConfig ?? config;
      if (!runtime) {
        return null;
      }
      try {
        const payload = await getWorkspaceBootstrap(runtime);
        setBootstrap(payload);
        setOnboardingStage(payload.onboarding.stage);
        setNeedsOnboarding(payload.onboarding.stage !== "ready");
        setConfigError(null);
        return payload;
      } catch (error) {
        setConfigError(toErrorMessage(error));
        return null;
      }
    },
    [config]
  );

  const ensureOnboarded = useCallback(
    async (runtimeConfig?: AppConfig): Promise<boolean> => {
      const payload = bootstrap ?? (await loadBootstrap(runtimeConfig));
      if (!payload) {
        return false;
      }
      return payload.onboarding.stage === "ready";
    },
    [bootstrap, loadBootstrap]
  );

  return {
    config,
    configError,
    needsOnboarding,
    onboardingStage,
    isReady: onboardingStage === "ready",
    bootstrap,
    setNeedsOnboarding,
    ensureOnboarded,
    refreshBootstrap: loadBootstrap,
    toasts,
    pushToast,
  };
}
