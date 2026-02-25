import { useEffect, useMemo, useState } from "react";

import { apiRequest, getEvidencePreview } from "@/lib/api";
import {
  isOnboardingRequiredError,
  parsePositiveInt,
  previewCacheKey,
  syncSelectionQuery,
  toErrorMessage,
} from "@/lib/hooks/runtime-utils";
import { useAppRuntime } from "@/lib/hooks/use-app-runtime";
import { ChangeFeedRecord, ChangeRecord, EvidencePreviewResponse, Input, InputOverrides } from "@/lib/types";

export type ChangeFilter = "all" | "unread";

export type EvidencePreviewState = {
  loading: boolean;
  error: string | null;
  data: EvidencePreviewResponse | null;
};

export function useFeedData() {
  const runtime = useAppRuntime();
  const { config, ensureOnboarded, needsOnboarding, setNeedsOnboarding, pushToast } = runtime;

  const [activeSourceId, setActiveSourceId] = useState<number | null>(null);
  const [sources, setSources] = useState<Input[]>([]);
  const [overrides, setOverrides] = useState<InputOverrides>({ input_id: 0, courses: [], tasks: [] });

  const [changes, setChanges] = useState<ChangeRecord[]>([]);
  const [changesLoading, setChangesLoading] = useState(false);
  const [changesError, setChangesError] = useState<string | null>(null);
  const [changeFilter, setChangeFilter] = useState<ChangeFilter>("all");
  const [changeSourceTypeFilter, setChangeSourceTypeFilter] = useState<"all" | "email" | "ics">("all");
  const [changeNotes, setChangeNotes] = useState<Record<number, string>>({});
  const [evidencePreviews, setEvidencePreviews] = useState<Record<string, EvidencePreviewState>>({});

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
    if (!config || needsOnboarding) {
      return;
    }
    void handleRefreshChanges();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [changeSourceTypeFilter, needsOnboarding]);

  useEffect(() => {
    if (!config) {
      return;
    }
    syncSelectionQuery(activeSourceId);
  }, [config, activeSourceId]);

  useEffect(() => {
    if (!config || !activeSourceId) {
      setOverrides({ input_id: 0, courses: [], tasks: [] });
      return;
    }
    const inputType = sources.find((row) => row.id === activeSourceId)?.type ?? null;
    if (inputType === "email") {
      setOverrides({ input_id: activeSourceId, courses: [], tasks: [] });
      return;
    }

    void (async () => {
      try {
        const payload = await apiRequest<InputOverrides>(config, `/v1/inputs/${activeSourceId}/overrides`);
        setOverrides(payload);
      } catch {
        setOverrides({ input_id: activeSourceId, courses: [], tasks: [] });
      }
    })();
  }, [config, activeSourceId, sources]);

  async function boot(runtimeConfig: NonNullable<typeof config>) {
    const onboarded = await ensureOnboarded(runtimeConfig);
    if (!onboarded) {
      setChanges([]);
      setChangeNotes({});
      setSources([]);
      return;
    }
    await Promise.all([loadSources(runtimeConfig), loadChangesFeed(runtimeConfig)]);
  }

  async function loadSources(runtimeConfig: NonNullable<typeof config>) {
    try {
      const rows = await apiRequest<Input[]>(runtimeConfig, "/v1/inputs");
      setSources(rows);
      setActiveSourceId((current) => {
        if (current && rows.some((item) => item.id === current)) {
          return current;
        }
        return rows[0]?.id ?? null;
      });
    } catch {
      setSources([]);
      setActiveSourceId(null);
    }
  }

  async function loadChangesFeed(runtimeConfig: NonNullable<typeof config>): Promise<ChangeFeedRecord[]> {
    const params = new URLSearchParams();
    params.set("limit", "200");
    if (changeSourceTypeFilter !== "all") {
      params.set("input_types", changeSourceTypeFilter);
    }
    const rows = await apiRequest<ChangeFeedRecord[]>(runtimeConfig, `/v1/feed?${params.toString()}`);
    setChanges(rows);
    setChangeNotes(Object.fromEntries(rows.map((item) => [item.id, item.viewed_note ?? ""])));
    return rows;
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
      if (isOnboardingRequiredError(error)) {
        setNeedsOnboarding(true);
        return;
      }
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

  async function handlePreviewEvidence(changeId: number, inputId: number, side: "before" | "after") {
    if (!config) {
      return;
    }
    const key = previewCacheKey(changeId, side);
    const existing = evidencePreviews[key];
    if (existing?.loading || existing?.data) {
      return;
    }

    setEvidencePreviews((current) => ({
      ...current,
      [key]: { loading: true, error: null, data: null },
    }));

    try {
      const payload = await getEvidencePreview(config, inputId, changeId, side);
      setEvidencePreviews((current) => ({
        ...current,
        [key]: { loading: false, error: null, data: payload },
      }));
    } catch (error) {
      setEvidencePreviews((current) => ({
        ...current,
        [key]: { loading: false, error: toErrorMessage(error), data: null },
      }));
    }
  }

  function setChangeNote(changeId: number, note: string) {
    setChangeNotes((current) => ({
      ...current,
      [changeId]: note,
    }));
  }

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

  function getCourseDisplayLabel(label: string) {
    return courseLabelMap.get(label) ?? label;
  }

  function getTaskDisplayTitle(uid: string, title: string) {
    return taskLabelMap.get(uid) ?? title;
  }

  return {
    ...runtime,
    activeSourceId,
    changeFilter,
    setChangeFilter,
    changeSourceTypeFilter,
    setChangeSourceTypeFilter,
    filteredChanges,
    changesLoading,
    changesError,
    handleRefreshChanges,
    handleToggleViewed,
    evidencePreviews,
    handlePreviewEvidence,
    changeNotes,
    setChangeNote,
    getTaskDisplayTitle,
    getCourseDisplayLabel,
  };
}
