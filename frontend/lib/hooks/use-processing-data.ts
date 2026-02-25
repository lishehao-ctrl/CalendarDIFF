import { FormEvent, useEffect, useMemo, useState } from "react";

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
import { HealthResponse, Input, InputDeadlines, InputOverrides, StatusResponse } from "@/lib/types";

export type TaskChoice = {
  uid: string;
  title: string;
};

export function useProcessingData() {
  const runtime = useAppRuntime();
  const { config, ensureOnboarded, pushToast, needsOnboarding, setNeedsOnboarding } = runtime;

  const [sources, setSources] = useState<Input[]>([]);
  const [activeSourceId, setActiveSourceId] = useState<number | null>(null);
  const [overrides, setOverrides] = useState<InputOverrides>({ input_id: 0, courses: [], tasks: [] });
  const [deadlines, setDeadlines] = useState<InputDeadlines>({
    input_id: 0,
    input_label: null,
    fetched_at_utc: "",
    total_deadlines: 0,
    courses: [],
  });

  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [scopedLoading, setScopedLoading] = useState(false);
  const [healthLoading, setHealthLoading] = useState(false);
  const [statusLoading, setStatusLoading] = useState(false);

  const [sourcesError, setSourcesError] = useState<string | null>(null);
  const [scopedError, setScopedError] = useState<string | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);

  const [courseBusy, setCourseBusy] = useState(false);
  const [taskBusy, setTaskBusy] = useState(false);
  const [courseOriginal, setCourseOriginal] = useState("");
  const [courseDisplay, setCourseDisplay] = useState("");
  const [taskUid, setTaskUid] = useState("");
  const [taskDisplayTitle, setTaskDisplayTitle] = useState("");

  const [manualSyncingSourceId, setManualSyncingSourceId] = useState<number | null>(null);
  const [manualSyncBusySourceId, setManualSyncBusySourceId] = useState<number | null>(null);
  const [manualSyncBusyMessage, setManualSyncBusyMessage] = useState<string | null>(null);
  const [manualSyncRetryAfterSeconds, setManualSyncRetryAfterSeconds] = useState<number | null>(null);
  const [manualSyncAutoRetried, setManualSyncAutoRetried] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const inputId = parsePositiveInt(params.get("input_id"));
    if (inputId !== null) {
      setActiveSourceId(inputId);
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
    syncSelectionQuery(activeSourceId);
  }, [config, activeSourceId]);

  async function boot(runtimeConfig: NonNullable<typeof config>) {
    const onboarded = await ensureOnboarded(runtimeConfig);
    if (!onboarded) {
      setSources([]);
      setActiveSourceId(null);
      return;
    }
    await Promise.all([loadHealth(), loadStatus(runtimeConfig)]);
    await loadSources(runtimeConfig);
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

  async function loadStatus(runtimeConfig?: NonNullable<typeof config>) {
    const runtimeConfigResolved = runtimeConfig ?? config;
    if (!runtimeConfigResolved) {
      return;
    }

    setStatusLoading(true);
    setStatusError(null);
    try {
      const payload = await apiRequest<StatusResponse>(runtimeConfigResolved, "/v1/status");
      setStatus(payload);
    } catch (error) {
      setStatusError(toErrorMessage(error));
    } finally {
      setStatusLoading(false);
    }
  }

  async function loadSources(runtimeConfig: NonNullable<typeof config>) {
    if (needsOnboarding) {
      setSources([]);
      setActiveSourceId(null);
      return;
    }
    setSourcesLoading(true);
    setSourcesError(null);

    try {
      const rows = await apiRequest<Input[]>(runtimeConfig, "/v1/inputs");
      setSources(rows);

      const nextActiveId = activeSourceId && rows.some((row) => row.id === activeSourceId) ? activeSourceId : rows[0]?.id ?? null;
      setActiveSourceId(nextActiveId);

      if (!nextActiveId) {
        setOverrides({ input_id: 0, courses: [], tasks: [] });
        setDeadlines({ input_id: 0, input_label: null, fetched_at_utc: "", total_deadlines: 0, courses: [] });
        return;
      }

      const nextSourceType = rows.find((row) => row.id === nextActiveId)?.type ?? null;
      await loadSourceScopedData(runtimeConfig, nextActiveId, nextSourceType);
    } catch (error) {
      if (isOnboardingRequiredError(error)) {
        setNeedsOnboarding(true);
        setSources([]);
        setActiveSourceId(null);
        return;
      }
      setSourcesError(toErrorMessage(error));
    } finally {
      setSourcesLoading(false);
    }
  }

  async function loadSourceScopedData(runtimeConfig: NonNullable<typeof config>, sourceId: number, sourceType: string | null) {
    setScopedLoading(true);
    setScopedError(null);

    try {
      const resolvedType = sourceType ?? sources.find((item) => item.id === sourceId)?.type ?? "ics";
      if (resolvedType === "email") {
        setOverrides({ input_id: sourceId, courses: [], tasks: [] });
        setDeadlines({ input_id: sourceId, input_label: null, fetched_at_utc: "", total_deadlines: 0, courses: [] });
        setCourseOriginal("");
        setTaskUid("");
        return;
      }

      const [overridePayload, deadlinePayload] = await Promise.all([
        apiRequest<InputOverrides>(runtimeConfig, `/v1/inputs/${sourceId}/overrides`),
        apiRequest<InputDeadlines>(runtimeConfig, `/v1/inputs/${sourceId}/deadlines`),
      ]);
      setOverrides(overridePayload);
      setDeadlines(deadlinePayload);

      const courseChoices = [...new Set(deadlinePayload.courses.map((course) => course.course_label))].sort();
      setCourseOriginal((current) => (current && courseChoices.includes(current) ? current : courseChoices[0] ?? ""));

      const taskChoices = deadlinePayload.courses
        .flatMap((course) => course.deadlines)
        .map((deadline) => deadline.uid)
        .sort((a, b) => a.localeCompare(b));
      setTaskUid((current) => (current && taskChoices.includes(current) ? current : taskChoices[0] ?? ""));
    } catch (error) {
      if (isOnboardingRequiredError(error)) {
        setNeedsOnboarding(true);
        return;
      }
      setScopedError(toErrorMessage(error));
    } finally {
      setScopedLoading(false);
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
    await Promise.all([loadSources(config), loadHealth(), loadStatus(config)]);
  }

  async function handleActiveSourceChange(sourceId: number) {
    if (!config) {
      return;
    }
    setActiveSourceId(sourceId);
    const sourceType = sources.find((row) => row.id === sourceId)?.type ?? null;
    await Promise.all([loadSourceScopedData(config, sourceId, sourceType), loadHealth(), loadStatus(config)]);
  }

  async function runManualSync(sourceId: number) {
    if (!config || manualSyncingSourceId !== null) {
      return;
    }

    const startedAt = Date.now();
    setManualSyncingSourceId(sourceId);
    setManualSyncBusySourceId(null);
    setManualSyncBusyMessage(null);
    setManualSyncRetryAfterSeconds(null);
    setManualSyncAutoRetried(false);

    try {
      const firstAttempt = await requestManualSync(config, sourceId);
      if (firstAttempt.kind === "success") {
        handleManualSyncResult(firstAttempt.result, pushToast);
        await Promise.all([loadSources(config), loadHealth(), loadStatus(config)]);
        return;
      }

      if (firstAttempt.kind === "busy") {
        const retryAfterSeconds = firstAttempt.detail.retry_after_seconds > 0
          ? firstAttempt.detail.retry_after_seconds
          : MANUAL_SYNC_BUSY_RETRY_SECONDS;
        setManualSyncBusySourceId(sourceId);
        setManualSyncBusyMessage(firstAttempt.detail.message);
        setManualSyncRetryAfterSeconds(retryAfterSeconds);
        setManualSyncAutoRetried(false);
        pushToast(`Sync is in progress. Auto retry in ${retryAfterSeconds}s`, "info");

        await sleep(retryAfterSeconds * 1000);
        setManualSyncAutoRetried(true);

        const secondAttempt = await requestManualSync(config, sourceId);
        if (secondAttempt.kind === "success") {
          setManualSyncBusySourceId(null);
          setManualSyncBusyMessage(null);
          setManualSyncRetryAfterSeconds(null);
          setManualSyncAutoRetried(false);
          handleManualSyncResult(secondAttempt.result, pushToast);
          await Promise.all([loadSources(config), loadHealth(), loadStatus(config)]);
          return;
        }

        if (secondAttempt.kind === "busy") {
          setManualSyncBusySourceId(sourceId);
          setManualSyncBusyMessage(secondAttempt.detail.message);
          setManualSyncRetryAfterSeconds(
            secondAttempt.detail.retry_after_seconds > 0
              ? secondAttempt.detail.retry_after_seconds
              : MANUAL_SYNC_BUSY_RETRY_SECONDS
          );
          pushToast("Sync is still in progress. Click Retry now.", "info");
          return;
        }

        setManualSyncBusySourceId(null);
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
      setManualSyncingSourceId((current) => (current === sourceId ? null : current));
    }
  }

  async function handleRetryManualSyncBusy() {
    if (manualSyncBusySourceId === null) {
      return;
    }
    await runManualSync(manualSyncBusySourceId);
  }

  async function handleSaveCourseRename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!config || !activeSourceId || !courseOriginal || !courseDisplay.trim()) {
      return;
    }

    setCourseBusy(true);
    try {
      await apiRequest(config, `/v1/inputs/${activeSourceId}/courses/rename`, {
        method: "PUT",
        body: JSON.stringify({
          original_course_label: courseOriginal,
          display_course_label: courseDisplay.trim(),
        }),
      });
      pushToast("Course rename saved", "success");
      setCourseDisplay("");
      await loadSourceScopedData(config, activeSourceId, null);
    } catch (error) {
      pushToast(`Course rename failed: ${toErrorMessage(error)}`, "error");
    } finally {
      setCourseBusy(false);
    }
  }

  async function handleDeleteCourseRename(originalLabel: string) {
    if (!config || !activeSourceId) {
      return;
    }

    try {
      await apiRequest(config, `/v1/inputs/${activeSourceId}/courses/rename?original_course_label=${encodeURIComponent(originalLabel)}`, {
        method: "DELETE",
      });
      pushToast("Course rename deleted", "info");
      await loadSourceScopedData(config, activeSourceId, null);
    } catch (error) {
      pushToast(`Delete failed: ${toErrorMessage(error)}`, "error");
    }
  }

  async function handleSaveTaskRename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!config || !activeSourceId || !taskUid || !taskDisplayTitle.trim()) {
      return;
    }

    setTaskBusy(true);
    try {
      await apiRequest(config, `/v1/inputs/${activeSourceId}/tasks/${encodeURIComponent(taskUid)}/rename`, {
        method: "PUT",
        body: JSON.stringify({ display_title: taskDisplayTitle.trim() }),
      });
      pushToast("Task rename saved", "success");
      setTaskDisplayTitle("");
      await loadSourceScopedData(config, activeSourceId, null);
    } catch (error) {
      pushToast(`Task rename failed: ${toErrorMessage(error)}`, "error");
    } finally {
      setTaskBusy(false);
    }
  }

  async function handleDeleteTaskRename(uid: string) {
    if (!config || !activeSourceId) {
      return;
    }

    try {
      await apiRequest(config, `/v1/inputs/${activeSourceId}/tasks/${encodeURIComponent(uid)}/rename`, {
        method: "DELETE",
      });
      pushToast("Task rename deleted", "info");
      await loadSourceScopedData(config, activeSourceId, null);
    } catch (error) {
      pushToast(`Delete failed: ${toErrorMessage(error)}`, "error");
    }
  }

  const courseSet = useMemo(() => {
    return [...new Set(deadlines.courses.map((course) => course.course_label))].sort();
  }, [deadlines]);

  const taskSet = useMemo<TaskChoice[]>(() => {
    return deadlines.courses
      .flatMap((course) => course.deadlines)
      .map((deadline) => ({ uid: deadline.uid, title: deadline.title }))
      .sort((a, b) => a.uid.localeCompare(b.uid));
  }, [deadlines]);

  const courseLabelMap = useMemo(() => {
    return new Map(overrides.courses.map((item) => [item.original_course_label, item.display_course_label]));
  }, [overrides.courses]);

  const taskLabelMap = useMemo(() => {
    return new Map(overrides.tasks.map((item) => [item.event_uid, item.display_title]));
  }, [overrides.tasks]);

  function getCourseDisplayLabel(label: string) {
    return courseLabelMap.get(label) ?? label;
  }

  function formatCourseOptionLabel(label: string) {
    const display = getCourseDisplayLabel(label);
    return display === label ? label : `${label} -> ${display}`;
  }

  function getTaskDisplayTitle(uid: string, title: string) {
    return taskLabelMap.get(uid) ?? title;
  }

  return {
    ...runtime,
    sources,
    activeSourceId,
    sourcesLoading,
    sourcesError,
    handleActiveSourceChange,
    handleRefreshSources,
    runManualSync,
    handleRetryManualSyncBusy,
    manualSyncingSourceId,
    manualSyncBusySourceId,
    manualSyncBusyMessage,
    manualSyncRetryAfterSeconds,
    manualSyncAutoRetried,
    healthError,
    healthLoading,
    scheduler: health?.scheduler,
    loadHealth,
    status,
    statusLoading,
    statusError,
    loadStatus,
    scopedError,
    scopedLoading,
    overrides,
    courseSet,
    courseOriginal,
    courseDisplay,
    setCourseOriginal,
    setCourseDisplay,
    courseBusy,
    handleSaveCourseRename,
    handleDeleteCourseRename,
    formatCourseOptionLabel,
    taskSet,
    taskUid,
    taskDisplayTitle,
    setTaskUid,
    setTaskDisplayTitle,
    taskBusy,
    handleSaveTaskRename,
    handleDeleteTaskRename,
    getTaskDisplayTitle,
  };
}
