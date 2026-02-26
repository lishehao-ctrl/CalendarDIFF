import { useEffect, useState } from "react";

import { apiRequest } from "@/lib/api";
import {
  handleManualSyncResult,
  isOnboardingRequiredError,
  MANUAL_SYNC_BUSY_RETRY_SECONDS,
  MIN_MANUAL_SYNC_ANIMATION_MS,
  parsePositiveInt,
  requestManualSync,
  sleep,
  syncSelectionQuery,
  toErrorMessage,
} from "@/lib/hooks/runtime-utils";
import { useAppRuntime } from "@/lib/hooks/use-app-runtime";
import { HealthResponse, Input } from "@/lib/types";

export function useProcessingData() {
  const runtime = useAppRuntime();
  const { config, ensureOnboarded, pushToast, needsOnboarding, setNeedsOnboarding } = runtime;

  const [inputs, setInputs] = useState<Input[]>([]);
  const [activeInputId, setActiveInputId] = useState<number | null>(null);

  const [inputsLoading, setInputsLoading] = useState(false);
  const [inputsError, setInputsError] = useState<string | null>(null);

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthError, setHealthError] = useState<string | null>(null);

  const [manualSyncingInputId, setManualSyncingInputId] = useState<number | null>(null);
  const [manualSyncBusyInputId, setManualSyncBusyInputId] = useState<number | null>(null);
  const [manualSyncBusyMessage, setManualSyncBusyMessage] = useState<string | null>(null);
  const [manualSyncRetryAfterSeconds, setManualSyncRetryAfterSeconds] = useState<number | null>(null);
  const [manualSyncAutoRetried, setManualSyncAutoRetried] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const inputId = parsePositiveInt(params.get("input_id"));
    if (inputId !== null) {
      setActiveInputId(inputId);
    }
  }, []);

  useEffect(() => {
    if (!config) {
      return;
    }
    void boot(config);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config]);

  useEffect(() => {
    if (!config) {
      return;
    }
    syncSelectionQuery(activeInputId);
  }, [config, activeInputId]);

  async function boot(runtimeConfig: NonNullable<typeof config>) {
    const onboarded = await ensureOnboarded(runtimeConfig);
    if (!onboarded) {
      setInputs([]);
      setActiveInputId(null);
      return;
    }
    await Promise.all([loadInputs(runtimeConfig), loadHealth()]);
  }

  async function loadHealth() {
    setHealthLoading(true);
    setHealthError(null);
    try {
      const response = await fetch("/health");
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`${response.status} ${response.statusText} - ${text}`);
      }
      setHealth((await response.json()) as HealthResponse);
    } catch (error) {
      setHealthError(toErrorMessage(error));
    } finally {
      setHealthLoading(false);
    }
  }

  async function loadInputs(runtimeConfig: NonNullable<typeof config>) {
    if (needsOnboarding) {
      setInputs([]);
      setActiveInputId(null);
      return;
    }
    setInputsLoading(true);
    setInputsError(null);
    try {
      const rows = (await apiRequest<Input[]>(runtimeConfig, "/v1/inputs")).filter((row) => row.is_active);
      setInputs(rows);
      setActiveInputId((current) => {
        if (current && rows.some((row) => row.id === current)) {
          return current;
        }
        return rows[0]?.id ?? null;
      });
    } catch (error) {
      if (isOnboardingRequiredError(error)) {
        setNeedsOnboarding(true);
        setInputs([]);
        setActiveInputId(null);
        return;
      }
      setInputsError(toErrorMessage(error));
    } finally {
      setInputsLoading(false);
    }
  }

  async function handleRefreshInputs() {
    if (!config) {
      return;
    }
    const onboarded = await ensureOnboarded(config);
    if (!onboarded) {
      return;
    }
    await Promise.all([loadInputs(config), loadHealth()]);
  }

  async function handleActiveInputChange(inputId: number) {
    setActiveInputId(inputId);
  }

  async function runManualSync(inputId: number) {
    if (!config || manualSyncingInputId !== null) {
      return;
    }

    const startedAt = Date.now();
    setManualSyncingInputId(inputId);
    setManualSyncBusyInputId(null);
    setManualSyncBusyMessage(null);
    setManualSyncRetryAfterSeconds(null);
    setManualSyncAutoRetried(false);

    try {
      const firstAttempt = await requestManualSync(config, inputId);
      if (firstAttempt.kind === "success") {
        handleManualSyncResult(firstAttempt.result, pushToast);
        await Promise.all([loadInputs(config), loadHealth()]);
        return;
      }

      if (firstAttempt.kind === "busy") {
        const retryAfterSeconds = firstAttempt.detail.retry_after_seconds > 0
          ? firstAttempt.detail.retry_after_seconds
          : MANUAL_SYNC_BUSY_RETRY_SECONDS;
        setManualSyncBusyInputId(inputId);
        setManualSyncBusyMessage(firstAttempt.detail.message);
        setManualSyncRetryAfterSeconds(retryAfterSeconds);
        setManualSyncAutoRetried(false);
        pushToast(`Sync is in progress. Auto retry in ${retryAfterSeconds}s`, "info");

        await sleep(retryAfterSeconds * 1000);
        setManualSyncAutoRetried(true);

        const secondAttempt = await requestManualSync(config, inputId);
        if (secondAttempt.kind === "success") {
          setManualSyncBusyInputId(null);
          setManualSyncBusyMessage(null);
          setManualSyncRetryAfterSeconds(null);
          setManualSyncAutoRetried(false);
          handleManualSyncResult(secondAttempt.result, pushToast);
          await Promise.all([loadInputs(config), loadHealth()]);
          return;
        }

        if (secondAttempt.kind === "busy") {
          setManualSyncBusyInputId(inputId);
          setManualSyncBusyMessage(secondAttempt.detail.message);
          setManualSyncRetryAfterSeconds(
            secondAttempt.detail.retry_after_seconds > 0
              ? secondAttempt.detail.retry_after_seconds
              : MANUAL_SYNC_BUSY_RETRY_SECONDS
          );
          pushToast("Sync is still in progress. Click Retry now.", "info");
          return;
        }

        setManualSyncBusyInputId(null);
        setManualSyncBusyMessage(null);
        setManualSyncRetryAfterSeconds(null);
        setManualSyncAutoRetried(false);
        pushToast(`Sync failed: ${secondAttempt.message}`, "error");
        return;
      }

      pushToast(`Sync failed: ${firstAttempt.message}`, "error");
    } catch (error) {
      pushToast(`Sync failed: ${toErrorMessage(error)}`, "error");
    } finally {
      const elapsed = Date.now() - startedAt;
      if (elapsed < MIN_MANUAL_SYNC_ANIMATION_MS) {
        await sleep(MIN_MANUAL_SYNC_ANIMATION_MS - elapsed);
      }
      setManualSyncingInputId((current) => (current === inputId ? null : current));
    }
  }

  async function handleRetryManualSyncBusy() {
    if (manualSyncBusyInputId === null) {
      return;
    }
    await runManualSync(manualSyncBusyInputId);
  }

  return {
    ...runtime,
    inputs,
    activeInputId,
    inputsLoading,
    inputsError,
    health,
    healthLoading,
    healthError,
    manualSyncingInputId,
    manualSyncBusyInputId,
    manualSyncBusyMessage,
    manualSyncRetryAfterSeconds,
    manualSyncAutoRetried,
    loadHealth,
    handleRefreshInputs,
    handleActiveInputChange,
    runManualSync,
    handleRetryManualSyncBusy,
  };
}
