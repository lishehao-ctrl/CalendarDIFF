import { useEffect, useState } from "react";

import {
  ApiError,
  applyEmailReview,
  getEmailQueue,
  getOnboardingStatus,
  markEmailViewed,
  updateEmailRoute,
} from "@/lib/api";
import { getRuntimeConfig } from "@/lib/config";
import { AppConfig, EmailQueueItem, EmailRoute } from "@/lib/types";
import { useToast } from "@/lib/hooks/use-toast";

export function useEmailReviewQueue() {
  const { toasts, pushToast } = useToast();
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [needsOnboarding, setNeedsOnboarding] = useState(false);

  const [items, setItems] = useState<EmailQueueItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [busyEmailId, setBusyEmailId] = useState<string | null>(null);
  const [lastAppliedChangeId, setLastAppliedChangeId] = useState<number | null>(null);

  useEffect(() => {
    const runtime = getRuntimeConfig();
    if (!runtime.apiKey) {
      setConfigError("Missing API key from /ui/app-config.js");
      return;
    }
    setConfig(runtime);
  }, []);

  useEffect(() => {
    if (!config) {
      return;
    }
    void (async () => {
      try {
        const onboarding = await getOnboardingStatus(config);
        if (onboarding.stage !== "ready") {
          setNeedsOnboarding(true);
          return;
        }
        setNeedsOnboarding(false);
        await loadQueue(config);
      } catch (err) {
        if (isOnboardingRequiredError(err)) {
          setNeedsOnboarding(true);
          return;
        }
        setError(toErrorMessage(err));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config]);

  async function loadQueue(runtimeConfig?: AppConfig) {
    const runtime = runtimeConfig ?? config;
    if (!runtime) {
      return;
    }
    setLoading(true);
    setRefreshing(true);
    setError(null);
    try {
      const rows = await getEmailQueue(runtime, { route: "review", limit: 50 });
      setItems(rows);
    } catch (err) {
      if (isOnboardingRequiredError(err)) {
        setNeedsOnboarding(true);
        return;
      }
      setError(toErrorMessage(err));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  async function handleMarkViewed(emailId: string) {
    if (!config) {
      return;
    }
    setBusyEmailId(emailId);
    try {
      const response = await markEmailViewed(config, emailId);
      setItems((current) =>
        current.map((item) =>
          item.email_id === emailId
            ? {
                ...item,
                flags: {
                  ...item.flags,
                  viewed: true,
                  viewed_at: response.viewed_at,
                },
              }
            : item
        )
      );
    } catch (err) {
      pushToast(toErrorMessage(err), "error");
    } finally {
      setBusyEmailId(null);
    }
  }

  async function handleRoute(emailId: string, route: EmailRoute) {
    if (!config) {
      return;
    }
    setBusyEmailId(emailId);
    try {
      await updateEmailRoute(config, emailId, { route });
      if (route === "review") {
        await loadQueue(config);
      } else {
        setItems((current) => current.filter((item) => item.email_id !== emailId));
      }
      pushToast(`Route updated: ${route}`, "success");
    } catch (err) {
      pushToast(toErrorMessage(err), "error");
    } finally {
      setBusyEmailId(null);
    }
  }

  async function handleApply(emailId: string) {
    if (!config) {
      return;
    }
    setBusyEmailId(emailId);
    try {
      const result = await applyEmailReview(config, emailId, {});
      setLastAppliedChangeId(result.change_id);
      setItems((current) => current.filter((item) => item.email_id !== emailId));
      pushToast(`Applied to timeline (change #${result.change_id})`, "success");
    } catch (err) {
      pushToast(toErrorMessage(err), "error");
    } finally {
      setBusyEmailId(null);
    }
  }

  return {
    toasts,
    configError,
    needsOnboarding,
    items,
    loading,
    refreshing,
    error,
    busyEmailId,
    lastAppliedChangeId,
    loadQueue,
    handleApply,
    handleRoute,
    handleMarkViewed,
  };
}

function toErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function isOnboardingRequiredError(error: unknown): boolean {
  if (!(error instanceof ApiError)) {
    return false;
  }
  if (error.status !== 404 && error.status !== 409) {
    return false;
  }
  const body = error.body;
  if (!body || typeof body !== "object") {
    return false;
  }
  const detail = (body as Record<string, unknown>).detail;
  if (!detail || typeof detail !== "object") {
    return false;
  }
  const code = (detail as Record<string, unknown>).code;
  return code === "user_not_initialized" || code === "user_onboarding_incomplete";
}
