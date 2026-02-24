import { FormEvent, useEffect, useMemo, useState } from "react";

import { apiRequest, ApiError, downloadEvidence } from "@/lib/api";
import { getRuntimeConfig } from "@/lib/config";
import {
  AppConfig,
  ChangeFeedRecord,
  ChangeRecord,
  GmailOAuthStartRequest,
  GmailOAuthStartResponse,
  HealthResponse,
  ManualSyncResponse,
  SourceBusyDetail,
  Source,
  SourceCreateResponse,
  SourceDeadlines,
  SourceOverrides,
  StatusResponse,
  UserTerm,
} from "@/lib/types";
import { ToastItem, ToastTone, useToast } from "@/lib/hooks/use-toast";

export type ChangeFilter = "all" | "unread";

export type TaskChoice = {
  uid: string;
  title: string;
};

const MIN_MANUAL_SYNC_ANIMATION_MS = 800;
const MANUAL_SYNC_BUSY_RETRY_SECONDS = 10;

export function useDashboardData() {
  const { toasts, pushToast } = useToast();

  const [config, setConfig] = useState<AppConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);

  const [activeUserTerms, setActiveUserTerms] = useState<UserTerm[]>([]);
  const [needsOnboarding, setNeedsOnboarding] = useState(false);

  const [sources, setSources] = useState<Source[]>([]);
  const [activeSourceId, setActiveSourceId] = useState<number | null>(null);
  const [overrides, setOverrides] = useState<SourceOverrides>({ input_id: 0, courses: [], tasks: [] });
  const [deadlines, setDeadlines] = useState<SourceDeadlines>({
    input_id: 0,
    input_label: null,
    fetched_at_utc: "",
    total_deadlines: 0,
    courses: [],
  });
  const [changes, setChanges] = useState<ChangeRecord[]>([]);
  const [changeFilter, setChangeFilter] = useState<ChangeFilter>("all");
  const [changeNotes, setChangeNotes] = useState<Record<number, string>>({});

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);

  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [scopedLoading, setScopedLoading] = useState(false);
  const [changesLoading, setChangesLoading] = useState(false);
  const [healthLoading, setHealthLoading] = useState(false);
  const [statusLoading, setStatusLoading] = useState(false);
  const [manualSyncingSourceId, setManualSyncingSourceId] = useState<number | null>(null);
  const [manualSyncStartedAt, setManualSyncStartedAt] = useState<number | null>(null);
  const [manualSyncBusySourceId, setManualSyncBusySourceId] = useState<number | null>(null);
  const [manualSyncBusyMessage, setManualSyncBusyMessage] = useState<string | null>(null);
  const [manualSyncRetryAfterSeconds, setManualSyncRetryAfterSeconds] = useState<number | null>(null);
  const [manualSyncAutoRetried, setManualSyncAutoRetried] = useState(false);

  const [sourcesError, setSourcesError] = useState<string | null>(null);
  const [scopedError, setScopedError] = useState<string | null>(null);
  const [changesError, setChangesError] = useState<string | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

  const [createBusy, setCreateBusy] = useState(false);
  const [courseBusy, setCourseBusy] = useState(false);
  const [taskBusy, setTaskBusy] = useState(false);

  const [changeSourceTypeFilter, setChangeSourceTypeFilter] = useState<"all" | "email" | "ics">("all");
  const [feedTermScope, setFeedTermScope] = useState<"current" | "all" | "term">("current");
  const [feedTermId, setFeedTermId] = useState<number | null>(null);

  const [sourceUrl, setSourceUrl] = useState("");
  const [sourceTermId, setSourceTermId] = useState<string>("");
  const [sourceEmailLabel, setSourceEmailLabel] = useState("");
  const [sourceEmailFromContains, setSourceEmailFromContains] = useState("");
  const [sourceEmailSubjectKeywords, setSourceEmailSubjectKeywords] = useState("");

  const [courseOriginal, setCourseOriginal] = useState("");
  const [courseDisplay, setCourseDisplay] = useState("");
  const [taskUid, setTaskUid] = useState("");
  const [taskDisplayTitle, setTaskDisplayTitle] = useState("");

  useEffect(() => {
    const runtimeConfig = getRuntimeConfig();
    if (!runtimeConfig.apiKey) {
      setConfigError("Missing API key from /ui/app-config.js");
      return;
    }

    const params = new URLSearchParams(window.location.search);
    const inputId = parsePositiveInt(params.get("input_id"));
    if (inputId !== null) {
      setActiveSourceId(inputId);
    }

    setConfig(runtimeConfig);
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
    const params = new URLSearchParams(window.location.search);
    const oauthStatus = params.get("gmail_oauth_status");
    if (!oauthStatus) {
      return;
    }

    const sourceIdParam = params.get("input_id");
    const message = params.get("message");
    if (oauthStatus === "success") {
      pushToast("Gmail connected successfully", "success");
      if (sourceIdParam) {
        const parsedId = Number(sourceIdParam);
        if (Number.isInteger(parsedId) && parsedId > 0) {
          setActiveSourceId(parsedId);
        }
      }
    } else {
      pushToast(`Gmail OAuth failed: ${message ?? "unknown error"}`, "error");
    }

    params.delete("gmail_oauth_status");
    params.delete("input_id");
    params.delete("message");
    const nextQuery = params.toString();
    window.history.replaceState({}, "", `${window.location.pathname}${nextQuery ? `?${nextQuery}` : ""}${window.location.hash}`);
    void (async () => {
      const initialized = await loadUsers(config);
      if (!initialized) {
        return;
      }
      await Promise.all([loadSources(config), loadHealth(), loadStatus(config)]);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config]);

  useEffect(() => {
    if (!config || needsOnboarding) {
      return;
    }
    void loadSources(config);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsOnboarding]);

  useEffect(() => {
    if (!config || needsOnboarding) {
      return;
    }
    void handleRefreshChanges();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [changeSourceTypeFilter, feedTermScope, feedTermId, needsOnboarding]);

  useEffect(() => {
    if (feedTermScope !== "term" && feedTermId !== null) {
      setFeedTermId(null);
    }
  }, [feedTermScope, feedTermId]);

  useEffect(() => {
    if (!config) {
      return;
    }
    syncSelectionQuery(activeSourceId);
  }, [config, activeSourceId]);

  async function boot(runtimeConfig: AppConfig) {
    const initialized = await loadUsers(runtimeConfig);
    if (!initialized) {
      setActiveUserTerms([]);
      setSources([]);
      setChanges([]);
      setChangeNotes({});
      setOverrides({ input_id: 0, courses: [], tasks: [] });
      setDeadlines({ input_id: 0, input_label: null, fetched_at_utc: "", total_deadlines: 0, courses: [] });
      return;
    }
    await Promise.all([loadHealth(), loadStatus(runtimeConfig)]);
    await loadSources(runtimeConfig);
  }

  async function loadUsers(runtimeConfig?: AppConfig): Promise<boolean> {
    const runtime = runtimeConfig ?? config;
    if (!runtime) {
      return false;
    }

    try {
      const [, terms] = await Promise.all([
        apiRequest<{
          id: number;
          email: string | null;
          notify_email: string | null;
          calendar_delay_seconds: number;
          created_at: string;
        }>(runtime, "/v1/user"),
        apiRequest<
          Array<{
            id: number;
            user_id: number;
            code: string;
            label: string;
            starts_on: string;
            ends_on: string;
            is_active: boolean;
            created_at: string;
            updated_at: string;
          }>
        >(
          runtime,
          "/v1/user/terms"
        ),
      ]);
      setConfigError(null);
      setActiveUserTerms(terms);
      setNeedsOnboarding(false);
      return true;
    } catch (error) {
      if (isUserNotInitializedError(error)) {
        setNeedsOnboarding(true);
        setActiveUserTerms([]);
        return false;
      }
      setConfigError(toErrorMessage(error));
      return false;
    }
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
      const payload = (await response.json()) as HealthResponse;
      setHealth(payload);
    } catch (error) {
      setHealthError(toErrorMessage(error));
    } finally {
      setHealthLoading(false);
    }
  }

  async function loadStatus(runtimeConfig?: AppConfig) {
    const runtime = runtimeConfig ?? config;
    if (!runtime) {
      return;
    }

    setStatusLoading(true);
    setStatusError(null);
    try {
      const payload = await apiRequest<StatusResponse>(runtime, "/v1/status");
      setStatus(payload);
    } catch (error) {
      setStatusError(toErrorMessage(error));
    } finally {
      setStatusLoading(false);
    }
  }

  async function loadSources(runtimeConfig: AppConfig) {
    if (needsOnboarding) {
      setSources([]);
      setActiveSourceId(null);
      return;
    }
    setSourcesLoading(true);
    setSourcesError(null);
    try {
      const rows = await apiRequest<Source[]>(runtimeConfig, "/v1/inputs");
      setSources(rows);
      setActiveSourceId((current) => {
        if (current && rows.some((row) => row.id === current)) {
          return current;
        }
        return rows.length ? rows[0].id : null;
      });

      if (!rows.length) {
        setOverrides({ input_id: 0, courses: [], tasks: [] });
        setDeadlines({ input_id: 0, input_label: null, fetched_at_utc: "", total_deadlines: 0, courses: [] });
        setChanges([]);
        setChangeNotes({});
      } else {
        const nextActive = activeSourceId && rows.some((row) => row.id === activeSourceId) ? activeSourceId : rows[0].id;
        const nextSourceType = rows.find((row) => row.id === nextActive)?.type ?? null;
        await loadSourceScopedData(runtimeConfig, nextActive, nextSourceType);
      }
    } catch (error) {
      setSourcesError(toErrorMessage(error));
    } finally {
      setSourcesLoading(false);
    }
  }

  async function loadSourceScopedData(runtimeConfig: AppConfig, sourceId: number | null, sourceType: string | null = null) {
    setScopedLoading(true);
    setChangesLoading(true);
    setScopedError(null);
    setChangesError(null);

    try {
      if (!sourceId) {
        await loadChangesFeed(runtimeConfig);
        return;
      }
      const resolvedType = sourceType ?? sources.find((item) => item.id === sourceId)?.type ?? "ics";
      if (resolvedType === "email") {
        const changePayload = await loadChangesFeed(runtimeConfig);
        setOverrides({ input_id: sourceId, courses: [], tasks: [] });
        setDeadlines({ input_id: sourceId, input_label: null, fetched_at_utc: "", total_deadlines: 0, courses: [] });
        setCourseOriginal("");
        setTaskUid("");
        setChanges(changePayload);
        setChangeNotes(Object.fromEntries(changePayload.map((item) => [item.id, item.viewed_note ?? ""])));
      } else {
        const [overridePayload, deadlinePayload] = await Promise.all([
          apiRequest<SourceOverrides>(runtimeConfig, `/v1/inputs/${sourceId}/overrides`),
          apiRequest<SourceDeadlines>(runtimeConfig, `/v1/inputs/${sourceId}/deadlines`),
        ]);
        const changePayload = await loadChangesFeed(runtimeConfig);

        setOverrides(overridePayload);
        setDeadlines(deadlinePayload);
        setChanges(changePayload);
        setChangeNotes(Object.fromEntries(changePayload.map((item) => [item.id, item.viewed_note ?? ""])));

        const courseChoices = [...new Set(deadlinePayload.courses.map((course) => course.course_label))].sort();
        setCourseOriginal((current) => (current && courseChoices.includes(current) ? current : courseChoices[0] ?? ""));

        const taskChoices = deadlinePayload.courses
          .flatMap((course) => course.deadlines)
          .map((deadline) => deadline.uid)
          .sort((a, b) => a.localeCompare(b));
        setTaskUid((current) => (current && taskChoices.includes(current) ? current : taskChoices[0] ?? ""));
      }
    } catch (error) {
      const message = toErrorMessage(error);
      setScopedError(message);
      setChangesError(message);
    } finally {
      setScopedLoading(false);
      setChangesLoading(false);
    }
  }

  async function loadChangesFeed(runtimeConfig: AppConfig): Promise<ChangeFeedRecord[]> {
    const params = new URLSearchParams();
    params.set("limit", "200");
    if (changeSourceTypeFilter !== "all") {
      params.set("input_types", changeSourceTypeFilter);
    }
    params.set("term_scope", feedTermScope);
    if (feedTermScope === "term" && feedTermId !== null) {
      params.set("term_id", String(feedTermId));
    }
    const rows = await apiRequest<ChangeFeedRecord[]>(runtimeConfig, `/v1/feed?${params.toString()}`);
    setChanges(rows);
    setChangeNotes(Object.fromEntries(rows.map((item) => [item.id, item.viewed_note ?? ""])));
    return rows;
  }

  async function handleRefreshSources() {
    if (!config) {
      return;
    }
    const initialized = await loadUsers(config);
    if (!initialized) {
      return;
    }
    await Promise.all([loadSources(config), loadHealth(), loadStatus(config)]);
  }

  async function handleActiveSourceChange(sourceId: number) {
    if (!config) {
      return;
    }
    setActiveSourceId(sourceId);
    const activeType = sources.find((row) => row.id === sourceId)?.type ?? null;
    await Promise.all([loadSourceScopedData(config, sourceId, activeType), loadHealth(), loadStatus(config)]);
  }

  async function runManualSync(sourceId: number) {
    if (!config) {
      return;
    }
    if (manualSyncingSourceId !== null) {
      return;
    }

    const startedAt = Date.now();
    setManualSyncingSourceId(sourceId);
    setManualSyncStartedAt(startedAt);
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
        const retryAfterSeconds =
          firstAttempt.detail.retry_after_seconds > 0 ? firstAttempt.detail.retry_after_seconds : MANUAL_SYNC_BUSY_RETRY_SECONDS;
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
      setManualSyncStartedAt(null);
    }
  }

  async function handleRetryManualSyncBusy() {
    if (manualSyncBusySourceId === null) {
      return;
    }
    await runManualSync(manualSyncBusySourceId);
  }

  async function handleCreateCalendarInput(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!config) {
      return;
    }
    if (!sourceUrl.trim()) {
      pushToast("ICS URL is required", "error");
      return;
    }

    let parsedTermId: number | null = null;
    if (sourceTermId.trim()) {
      const next = Number(sourceTermId);
      if (!Number.isInteger(next) || next <= 0) {
        pushToast("Term is invalid", "error");
        return;
      }
      parsedTermId = next;
    }

    setCreateBusy(true);
    try {
      const payload = {
        url: sourceUrl.trim(),
        user_term_id: parsedTermId,
      };

      const created = await apiRequest<SourceCreateResponse>(config, "/v1/inputs/ics", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      setSourceUrl("");
      setActiveSourceId(created.id);
      await Promise.all([loadSources(config), loadHealth(), loadStatus(config)]);

      if (created.upserted_existing) {
        pushToast("Calendar input updated (matched existing identity)", "info");
      } else {
        pushToast("Calendar input created", "success");
      }
    } catch (error) {
      pushToast(`Create input failed: ${toErrorMessage(error)}`, "error");
    } finally {
      setCreateBusy(false);
    }
  }

  async function handleConnectGmailInput(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!config) {
      return;
    }

    setCreateBusy(true);
    try {
      const keywords = sourceEmailSubjectKeywords
        .split(",")
        .map((item) => item.trim())
        .filter((item) => item.length > 0);
      const payload: GmailOAuthStartRequest = {
        label: sourceEmailLabel.trim() || null,
        from_contains: sourceEmailFromContains.trim() || null,
        subject_keywords: keywords.length ? keywords : null,
      };
      const oauthStart = await apiRequest<GmailOAuthStartResponse>(
        config,
        "/v1/inputs/email/gmail/oauth/start",
        {
          method: "POST",
          body: JSON.stringify(payload),
        }
      );
      window.location.assign(oauthStart.authorization_url);
    } catch (error) {
      pushToast(`Connect Gmail failed: ${toErrorMessage(error)}`, "error");
    } finally {
      setCreateBusy(false);
    }
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
      await loadSourceScopedData(config, activeSourceId);
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
      await loadSourceScopedData(config, activeSourceId);
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
      await loadSourceScopedData(config, activeSourceId);
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
      await loadSourceScopedData(config, activeSourceId);
    } catch (error) {
      pushToast(`Delete failed: ${toErrorMessage(error)}`, "error");
    }
  }

  async function handleRefreshChanges() {
    if (!config || needsOnboarding) {
      return;
    }
    setChangesLoading(true);
    setChangesError(null);
    try {
      await loadChangesFeed(config);
    } catch (error) {
      setChangesError(toErrorMessage(error));
    } finally {
      setChangesLoading(false);
    }
  }

  async function handleToggleViewed(change: ChangeRecord) {
    if (!config) {
      return;
    }

    const nextViewed = change.viewed_at === null;
    const note = nextViewed ? (changeNotes[change.id] || "").trim() || null : null;

    try {
      await apiRequest(config, `/v1/inputs/${change.input_id}/changes/${change.id}/viewed`, {
        method: "PATCH",
        body: JSON.stringify({ viewed: nextViewed, note }),
      });
      pushToast("Change viewed status updated", "success");
      await handleRefreshChanges();
    } catch (error) {
      pushToast(`Update viewed failed: ${toErrorMessage(error)}`, "error");
    }
  }

  async function handleDownloadEvidence(changeId: number, side: "before" | "after") {
    if (!config) {
      return;
    }
    try {
      const record = changes.find((item) => item.id === changeId);
      if (!record) {
        throw new Error("Change record not found");
      }
      await downloadEvidence(config, record.input_id, changeId, side);
      pushToast(`Downloaded ${side} evidence`, "info");
    } catch (error) {
      pushToast(`Download failed: ${toErrorMessage(error)}`, "error");
    }
  }

  function setChangeNote(changeId: number, note: string) {
    setChangeNotes((current) => ({
      ...current,
      [changeId]: note,
    }));
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

  const filteredChanges = useMemo(() => {
    if (changeFilter === "unread") {
      return changes.filter((item) => item.viewed_at === null);
    }
    return changes;
  }, [changeFilter, changes]);

  const courseLabelMap = useMemo(() => {
    return new Map(overrides.courses.map((item) => [item.original_course_label, item.display_course_label]));
  }, [overrides.courses]);

  const taskLabelMap = useMemo(() => {
    return new Map(overrides.tasks.map((item) => [item.event_uid, item.display_title]));
  }, [overrides.tasks]);

  const showDevTools = useMemo(() => {
    return Boolean(config?.enableDevEndpoints && (config?.appEnv ?? "").toLowerCase() === "dev");
  }, [config]);

  function getCourseDisplayLabel(label: string) {
    return courseLabelMap.get(label) ?? label;
  }

  function formatCourseOptionLabel(label: string) {
    const display = getCourseDisplayLabel(label);
    if (display === label) {
      return label;
    }
    return `${label} -> ${display}`;
  }

  function getTaskDisplayTitle(uid: string, title: string) {
    return taskLabelMap.get(uid) ?? title;
  }

  return {
    configError,
    showDevTools,
    toasts,
    needsOnboarding,

    sourceUrl,
    sourceTermId,
    sourceEmailLabel,
    sourceEmailFromContains,
    sourceEmailSubjectKeywords,
    setSourceUrl,
    setSourceTermId,
    setSourceEmailLabel,
    setSourceEmailFromContains,
    setSourceEmailSubjectKeywords,

    createBusy,
    handleCreateCalendarInput,
    handleConnectGmailInput,

    sources,
    activeSourceId,
    sourcesLoading,
    sourcesError,
    handleActiveSourceChange,
    handleRefreshSources,
    runManualSync,
    handleRetryManualSyncBusy,
    manualSyncingSourceId,
    manualSyncStartedAt,
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

    changeFilter,
    setChangeFilter,
    changeSourceTypeFilter,
    setChangeSourceTypeFilter,
    feedTermScope,
    setFeedTermScope,
    feedTermId,
    setFeedTermId,
    activeUserTerms,
    filteredChanges,
    changesLoading,
    changesError,
    handleRefreshChanges,
    handleToggleViewed,
    handleDownloadEvidence,
    changeNotes,
    setChangeNote,
    getCourseDisplayLabel,

    pushToast,
  };
}

function toErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function isUserNotInitializedError(error: unknown): boolean {
  if (!(error instanceof ApiError)) {
    return false;
  }
  if (error.status !== 404) {
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
  return (detail as Record<string, unknown>).code === "user_not_initialized";
}

export type DashboardDataHook = ReturnType<typeof useDashboardData>;
export type DashboardToastItem = ToastItem;
export type DashboardToastTone = ToastTone;

function parsePositiveInt(raw: string | null): number | null {
  if (!raw) {
    return null;
  }
  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    return null;
  }
  return parsed;
}

function syncSelectionQuery(inputId: number | null): void {
  const url = new URL(window.location.href);
  if (inputId === null) {
    url.searchParams.delete("input_id");
  } else {
    url.searchParams.set("input_id", String(inputId));
  }
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

type ManualSyncRequestResult =
  | { kind: "success"; result: ManualSyncResponse }
  | { kind: "busy"; detail: SourceBusyDetail }
  | { kind: "error"; message: string };

function handleManualSyncResult(
  result: ManualSyncResponse,
  pushToast: (message: string, tone: ToastTone) => void,
): void {
  if (result.last_error) {
    pushToast(`Sync failed: ${result.last_error}`, "error");
  } else if (result.notification_state === "queued_delayed_by_email_priority") {
    pushToast("Calendar changes queued, notification will be sent in ~2m", "info");
  } else if (result.is_baseline_sync || result.changes_created === 0) {
    pushToast("Checked just now — no changes", "info");
  } else if (result.email_sent) {
    pushToast(`Detected ${result.changes_created} changes — email sent`, "success");
  } else {
    pushToast(`Detected ${result.changes_created} changes — email not sent`, "info");
  }
}

async function requestManualSync(config: AppConfig, sourceId: number): Promise<ManualSyncRequestResult> {
  try {
    const result = await apiRequest<ManualSyncResponse>(config, `/v1/inputs/${sourceId}/sync`, {
      method: "POST",
    });
    return { kind: "success", result };
  } catch (error) {
    const busy = readSourceBusyDetail(error);
    if (busy) {
      return { kind: "busy", detail: busy };
    }
    return { kind: "error", message: toErrorMessage(error) };
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function readSourceBusyDetail(error: unknown): SourceBusyDetail | null {
  if (!(error instanceof ApiError) || error.status !== 409) {
    return null;
  }
  if (!error.body || typeof error.body !== "object") {
    return null;
  }
  const detail = (error.body as Record<string, unknown>).detail;
  if (!detail || typeof detail !== "object") {
    return null;
  }

  const code = (detail as Record<string, unknown>).code;
  const status = (detail as Record<string, unknown>).status;
  const message = (detail as Record<string, unknown>).message;
  const retryAfter = (detail as Record<string, unknown>).retry_after_seconds;
  const recoverable = (detail as Record<string, unknown>).recoverable;
  if (code !== "source_busy") {
    return null;
  }
  if (typeof message !== "string") {
    return null;
  }
  if (typeof retryAfter !== "number" || !Number.isFinite(retryAfter)) {
    return null;
  }
  if (typeof recoverable !== "boolean") {
    return null;
  }

  return {
    status: status === "LOCK_SKIPPED" ? "LOCK_SKIPPED" : undefined,
    code: "source_busy",
    message,
    retry_after_seconds: retryAfter,
    recoverable,
  };
}
