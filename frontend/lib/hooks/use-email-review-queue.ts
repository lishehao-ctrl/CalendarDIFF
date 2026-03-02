import { useEffect, useState } from "react";

import { getEmailReviewQueue, markEmailViewed, updateEmailRoute } from "@/lib/api";
import { toErrorMessage } from "@/lib/hooks/runtime-utils";
import { useAppRuntime } from "@/lib/hooks/use-app-runtime";
import { EmailQueueItem, EmailRoute } from "@/lib/types";

export function useEmailReviewQueue() {
  const runtime = useAppRuntime();
  const { toasts, pushToast, config, configError, needsOnboarding, ensureOnboarded } = runtime;
  const [items, setItems] = useState<EmailQueueItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [busyEmailId, setBusyEmailId] = useState<string | null>(null);

  useEffect(() => {
    if (!config) {
      return;
    }
    void boot(config);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config]);

  async function boot(runtimeConfig: NonNullable<typeof config>) {
    const onboarded = await ensureOnboarded(runtimeConfig);
    if (!onboarded) {
      return;
    }
    await loadQueue(runtimeConfig);
  }

  async function loadQueue(runtimeConfig?: NonNullable<typeof config>) {
    const runtimeInput = runtimeConfig ?? config;
    if (!runtimeInput) {
      return;
    }
    setLoading(true);
    setRefreshing(true);
    setError(null);
    try {
      const rows = await getEmailReviewQueue(runtimeInput, { route: "review", limit: 50 });
      setItems(rows);
    } catch (err) {
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

  return {
    toasts,
    configError,
    needsOnboarding,
    items,
    loading,
    refreshing,
    error,
    busyEmailId,
    loadQueue,
    handleRoute,
    handleMarkViewed,
  };
}
