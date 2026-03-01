import { useEffect, useState } from "react";

import { getHealth } from "@/lib/api";
import {
  handleManualSyncResult,
  isOnboardingRequiredError,
  MIN_MANUAL_SYNC_ANIMATION_MS,
  parsePositiveInt,
  requestManualSync,
  sleep,
  syncSelectionQuery,
  toErrorMessage,
} from "@/lib/hooks/runtime-utils";
import { useAppRuntime } from "@/lib/hooks/use-app-runtime";
import { HealthResponse, InputSource } from "@/lib/types";

export function useProcessingData() {
  const runtime = useAppRuntime();
  const { config, ensureOnboarded, pushToast, needsOnboarding, setNeedsOnboarding, sources, refreshRuntime } = runtime;

  const [sourceRows, setSourceRows] = useState<InputSource[]>([]);
  const [activeSourceId, setActiveSourceId] = useState<number | null>(null);

  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [sourcesError, setSourcesError] = useState<string | null>(null);

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthError, setHealthError] = useState<string | null>(null);

  const [manualSyncingSourceId, setManualSyncingSourceId] = useState<number | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sourceId = parsePositiveInt(params.get("source_id"));
    if (sourceId !== null) {
      setActiveSourceId(sourceId);
    }
  }, []);

  useEffect(() => {
    applySources(sources);
  }, [sources]);

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
    syncSelectionQuery(activeSourceId);
  }, [config, activeSourceId]);

  async function boot(runtimeConfig: NonNullable<typeof config>) {
    const onboarded = await ensureOnboarded(runtimeConfig);
    if (!onboarded) {
      setSourceRows([]);
      setActiveSourceId(null);
      return;
    }
    const snapshot = await refreshRuntime(runtimeConfig);
    if (snapshot) {
      applySources(snapshot.sources);
    }
    await loadHealth(runtimeConfig);
  }

  function applySources(rows: InputSource[]) {
    const activeRows = rows.filter((row) => row.is_active);
    setSourceRows(activeRows);
    setActiveSourceId((current) => {
      if (current && activeRows.some((row) => row.source_id === current)) {
        return current;
      }
      return activeRows[0]?.source_id ?? null;
    });
  }

  async function loadHealth(runtimeConfig?: NonNullable<typeof config>) {
    const activeConfig = runtimeConfig ?? config;
    if (!activeConfig) {
      return;
    }
    setHealthLoading(true);
    setHealthError(null);
    try {
      const payload = await getHealth(activeConfig);
      setHealth(payload);
    } catch (error) {
      setHealthError(toErrorMessage(error));
    } finally {
      setHealthLoading(false);
    }
  }

  async function loadSources(runtimeConfig: NonNullable<typeof config>) {
    if (needsOnboarding) {
      setSourceRows([]);
      setActiveSourceId(null);
      return;
    }
    setSourcesLoading(true);
    setSourcesError(null);
    try {
      const snapshot = await refreshRuntime(runtimeConfig);
      applySources(snapshot?.sources ?? []);
    } catch (error) {
      if (isOnboardingRequiredError(error)) {
        setNeedsOnboarding(true);
        setSourceRows([]);
        setActiveSourceId(null);
        return;
      }
      setSourcesError(toErrorMessage(error));
    } finally {
      setSourcesLoading(false);
    }
  }

  async function handleRefreshSources() {
    if (!config) {
      return;
    }
    const onboarded = await ensureOnboarded(config);
    if (!onboarded) {
      return;
    }
    await Promise.all([loadSources(config), loadHealth(config)]);
  }

  async function handleActiveSourceChange(sourceId: number) {
    setActiveSourceId(sourceId);
  }

  async function runManualSync(sourceId: number) {
    if (!config || manualSyncingSourceId !== null) {
      return;
    }

    const startedAt = Date.now();
    setManualSyncingSourceId(sourceId);

    try {
      const attempt = await requestManualSync(config, sourceId);
      if (attempt.kind === "success") {
        handleManualSyncResult(attempt.result, pushToast);
        await Promise.all([loadSources(config), loadHealth(config)]);
        return;
      }
      pushToast(`Sync failed: ${attempt.message}`, "error");
    } catch (error) {
      pushToast(`Sync failed: ${toErrorMessage(error)}`, "error");
    } finally {
      const elapsed = Date.now() - startedAt;
      if (elapsed < MIN_MANUAL_SYNC_ANIMATION_MS) {
        await sleep(MIN_MANUAL_SYNC_ANIMATION_MS - elapsed);
      }
      setManualSyncingSourceId((current) => (current === sourceId ? null : current));
    }
  }

  async function handleRetryManualSyncBusy() {
    if (activeSourceId === null) {
      return;
    }
    await runManualSync(activeSourceId);
  }

  return {
    ...runtime,
    sourceRows,
    activeSourceId,
    sourcesLoading,
    sourcesError,
    health,
    healthLoading,
    healthError,
    manualSyncingSourceId,
    manualSyncBusySourceId: null as number | null,
    manualSyncBusyMessage: null as string | null,
    manualSyncRetryAfterSeconds: null as number | null,
    manualSyncAutoRetried: false,
    loadHealth,
    handleRefreshSources,
    handleActiveSourceChange,
    runManualSync,
    handleRetryManualSyncBusy,
  };
}
