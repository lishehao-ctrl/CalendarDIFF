import { useEffect, useMemo, useState } from "react";

import { getFeed, patchChangeViewed } from "@/lib/api";
import {
  isOnboardingRequiredError,
  parsePositiveInt,
  syncSelectionQuery,
  toErrorMessage,
} from "@/lib/hooks/runtime-utils";
import { useAppRuntime } from "@/lib/hooks/use-app-runtime";
import { ChangeFeedRecord } from "@/lib/types";

export type ChangeFilter = "all" | "unread";

export function useFeedData() {
  const runtime = useAppRuntime();
  const { config, ensureOnboarded, needsOnboarding, setNeedsOnboarding, pushToast, bootstrap } = runtime;

  const [activeSourceId, setActiveSourceId] = useState<number | null>(null);

  const [changes, setChanges] = useState<ChangeFeedRecord[]>([]);
  const [changesLoading, setChangesLoading] = useState(false);
  const [changesError, setChangesError] = useState<string | null>(null);
  const [changeFilter, setChangeFilter] = useState<ChangeFilter>("all");
  const [changeSourceTypeFilter, setChangeSourceTypeFilter] = useState<"all" | "email" | "ics">("all");
  const [changeNotes, setChangeNotes] = useState<Record<number, string>>({});

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const inputId = parsePositiveInt(params.get("input_id"));
    if (inputId !== null) {
      setActiveSourceId(inputId);
    }
  }, []);

  useEffect(() => {
    if (!bootstrap) {
      return;
    }
    const rows = bootstrap.inputs.filter((item) => item.is_active);
    setActiveSourceId((current) => {
      if (current && rows.some((item) => item.id === current)) {
        return current;
      }
      return rows[0]?.id ?? null;
    });
  }, [bootstrap]);

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

  async function boot(runtimeConfig: NonNullable<typeof config>) {
    const onboarded = await ensureOnboarded(runtimeConfig);
    if (!onboarded) {
      setChanges([]);
      setChangeNotes({});
      return;
    }
    await loadChangesFeed(runtimeConfig);
  }

  async function loadChangesFeed(runtimeConfig: NonNullable<typeof config>): Promise<ChangeFeedRecord[]> {
    const rows = await getFeed(runtimeConfig, {
      limit: 200,
      input_types: changeSourceTypeFilter === "all" ? undefined : changeSourceTypeFilter,
    });
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

  async function handleToggleViewed(change: ChangeFeedRecord) {
    if (!config) {
      return;
    }

    const nextViewed = change.viewed_at === null;
    const note = nextViewed ? (changeNotes[change.id] || "").trim() || null : null;

    try {
      await patchChangeViewed(config, change.id, { viewed: nextViewed, note });
      pushToast("Change viewed status updated", "success");
      await handleRefreshChanges();
    } catch (error) {
      pushToast(`Update viewed failed: ${toErrorMessage(error)}`, "error");
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
    changeNotes,
    setChangeNote,
  };
}
