import { useCallback, useEffect, useState } from "react";

import { ApiError, getCurrentUser, getInputSources, getOnboardingStatus } from "@/lib/api";
import { getRuntimeConfig } from "@/lib/config";
import { toErrorMessage } from "@/lib/hooks/runtime-utils";
import { useToast } from "@/lib/hooks/use-toast";
import { AppConfig, DashboardUser, InputSource, OnboardingStage, OnboardingStatus } from "@/lib/types";

type RuntimeSnapshot = {
  onboarding: OnboardingStatus;
  user: DashboardUser | null;
  sources: InputSource[];
};

const NOT_READY_CODES = new Set(["user_not_initialized", "user_onboarding_incomplete"]);

export function useAppRuntime() {
  const { toasts, pushToast } = useToast();

  const [config, setConfig] = useState<AppConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [needsOnboarding, setNeedsOnboarding] = useState(false);
  const [onboardingStage, setOnboardingStage] = useState<OnboardingStage | null>(null);
  const [onboardingStatus, setOnboardingStatus] = useState<OnboardingStatus | null>(null);
  const [user, setUser] = useState<DashboardUser | null>(null);
  const [sources, setSources] = useState<InputSource[]>([]);

  useEffect(() => {
    const runtimeConfig = getRuntimeConfig();
    if (!runtimeConfig.apiKey) {
      setConfigError("Missing API key from /ui/app-config.js");
      return;
    }
    setConfig(runtimeConfig);
    void loadRuntime(runtimeConfig);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadRuntime = useCallback(
    async (runtimeConfig?: AppConfig): Promise<RuntimeSnapshot | null> => {
      const runtime = runtimeConfig ?? config;
      if (!runtime) {
        return null;
      }

      try {
        const onboardingPromise = getOnboardingStatus(runtime);
        const userPromise = getCurrentUser(runtime).catch((error) => {
          if (isRuntimeNotReadyApiError(error)) {
            return null;
          }
          throw error;
        });
        const sourcesPromise = getInputSources(runtime).catch((error) => {
          if (isRuntimeNotReadyApiError(error)) {
            return [];
          }
          throw error;
        });

        const [onboarding, userPayload, sourcePayload] = await Promise.all([
          onboardingPromise,
          userPromise,
          sourcesPromise,
        ]);

        setOnboardingStatus(onboarding);
        setOnboardingStage(onboarding.stage);
        setNeedsOnboarding(onboarding.stage !== "ready");
        setUser(userPayload);
        setSources(sourcePayload);
        setConfigError(null);

        return {
          onboarding,
          user: userPayload,
          sources: sourcePayload,
        };
      } catch (error) {
        setConfigError(toErrorMessage(error));
        return null;
      }
    },
    [config]
  );

  const ensureOnboarded = useCallback(
    async (runtimeConfig?: AppConfig): Promise<boolean> => {
      const snapshot = onboardingStatus ? { onboarding: onboardingStatus, user, sources } : await loadRuntime(runtimeConfig);
      if (!snapshot) {
        return false;
      }
      return snapshot.onboarding.stage === "ready";
    },
    [loadRuntime, onboardingStatus, sources, user]
  );

  return {
    config,
    configError,
    needsOnboarding,
    onboardingStage,
    onboardingStatus,
    isReady: onboardingStage === "ready",
    user,
    sources,
    setNeedsOnboarding,
    ensureOnboarded,
    refreshRuntime: loadRuntime,
    toasts,
    pushToast,
  };
}

function isRuntimeNotReadyApiError(error: unknown): boolean {
  if (!(error instanceof ApiError)) {
    return false;
  }
  if (error.status !== 404 && error.status !== 409) {
    return false;
  }
  if (!error.body || typeof error.body !== "object") {
    return false;
  }
  const detail = (error.body as Record<string, unknown>).detail;
  if (!detail || typeof detail !== "object") {
    return false;
  }
  const code = (detail as Record<string, unknown>).code;
  return typeof code === "string" && NOT_READY_CODES.has(code);
}
