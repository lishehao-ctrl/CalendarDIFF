import { useEffect, useState } from "react";

import { ApiError, deleteInput, getEvents, getInputs, startGmailOAuth } from "@/lib/api";
import {
  isOnboardingRequiredError,
  parsePositiveInt,
  syncSelectionQuery,
  toErrorMessage,
} from "@/lib/hooks/runtime-utils";
import { useAppRuntime } from "@/lib/hooks/use-app-runtime";
import { EventListItem, Input } from "@/lib/types";

export function useInputsSettingsData() {
  const runtime = useAppRuntime();
  const { config, ensureOnboarded, needsOnboarding, setNeedsOnboarding, pushToast } = runtime;

  const [inputs, setInputs] = useState<Input[]>([]);
  const [inputsLoading, setInputsLoading] = useState(false);
  const [inputsError, setInputsError] = useState<string | null>(null);

  const [events, setEvents] = useState<EventListItem[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [eventsError, setEventsError] = useState<string | null>(null);

  const [activeInputId, setActiveInputId] = useState<number | null>(null);
  const [eventTypeFilter, setEventTypeFilter] = useState<"all" | "ics" | "email">("all");
  const [eventSearch, setEventSearch] = useState("");

  const [deletingInputId, setDeletingInputId] = useState<number | null>(null);
  const [connectingGmail, setConnectingGmail] = useState(false);
  const [oauthQueryHandled, setOauthQueryHandled] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const inputId = parsePositiveInt(params.get("input_id"));
    if (inputId !== null) {
      setActiveInputId(inputId);
    }
  }, []);

  useEffect(() => {
    if (!config || oauthQueryHandled) {
      return;
    }
    const params = new URLSearchParams(window.location.search);
    const oauthStatus = params.get("gmail_oauth_status");
    const oauthInputId = parsePositiveInt(params.get("input_id"));
    const oauthMessage = params.get("message");

    if (oauthStatus === "success") {
      pushToast(
        oauthInputId ? `Gmail connected (input-${oauthInputId})` : "Gmail connected",
        "success"
      );
      if (oauthInputId !== null) {
        setActiveInputId(oauthInputId);
      }
    } else if (oauthStatus === "error") {
      pushToast(`Gmail connect failed: ${oauthMessage || "unknown error"}`, "error");
    }

    if (oauthStatus) {
      params.delete("gmail_oauth_status");
      params.delete("message");
      const query = params.toString();
      window.history.replaceState({}, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
    }
    setOauthQueryHandled(true);
  }, [config, oauthQueryHandled, pushToast]);

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

  useEffect(() => {
    if (!config || needsOnboarding) {
      return;
    }
    void loadEvents(config);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config, needsOnboarding, activeInputId, eventTypeFilter, eventSearch]);

  async function boot(runtimeConfig: NonNullable<typeof config>) {
    const onboarded = await ensureOnboarded(runtimeConfig);
    if (!onboarded) {
      setInputs([]);
      setEvents([]);
      setActiveInputId(null);
      return;
    }
    await Promise.all([loadInputs(runtimeConfig), loadEvents(runtimeConfig)]);
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
      const rows = await getInputs(runtimeConfig);
      setInputs(rows);
      const firstActive = rows.find((row) => row.is_active) ?? rows[0] ?? null;
      setActiveInputId((current) => {
        if (current && rows.some((row) => row.id === current)) {
          return current;
        }
        return firstActive?.id ?? null;
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

  async function loadEvents(runtimeConfig: NonNullable<typeof config>) {
    if (needsOnboarding) {
      setEvents([]);
      return;
    }
    setEventsLoading(true);
    setEventsError(null);
    try {
      const rows = await getEvents(runtimeConfig, {
        input_id: activeInputId ?? undefined,
        input_type: eventTypeFilter === "all" ? undefined : eventTypeFilter,
        q: eventSearch.trim() || undefined,
        limit: 200,
        offset: 0,
      });
      setEvents(rows);
    } catch (error) {
      if (isOnboardingRequiredError(error)) {
        setNeedsOnboarding(true);
        setEvents([]);
        return;
      }
      setEventsError(toErrorMessage(error));
    } finally {
      setEventsLoading(false);
    }
  }

  async function handleRefresh() {
    if (!config) {
      return;
    }
    const onboarded = await ensureOnboarded(config);
    if (!onboarded) {
      return;
    }
    await Promise.all([loadInputs(config), loadEvents(config)]);
  }

  async function handleDeleteInput(inputId: number) {
    if (!config || deletingInputId !== null) {
      return;
    }
    setDeletingInputId(inputId);
    try {
      await deleteInput(config, inputId);
      pushToast(`Input input-${inputId} deactivated`, "success");
      await Promise.all([loadInputs(config), loadEvents(config)]);
    } catch (error) {
      const inactiveDetail = readApiDetailMessage(error);
      pushToast(inactiveDetail ?? toErrorMessage(error), "error");
    } finally {
      setDeletingInputId(null);
    }
  }

  async function handleConnectGmail() {
    if (!config || connectingGmail) {
      return;
    }
    setConnectingGmail(true);
    try {
      const response = await startGmailOAuth(config, {});
      window.location.assign(response.authorization_url);
    } catch (error) {
      pushToast(`Gmail OAuth start failed: ${toErrorMessage(error)}`, "error");
      setConnectingGmail(false);
    }
  }

  return {
    ...runtime,
    inputs,
    inputsLoading,
    inputsError,
    events,
    eventsLoading,
    eventsError,
    activeInputId,
    eventTypeFilter,
    eventSearch,
    deletingInputId,
    connectingGmail,
    setActiveInputId,
    setEventTypeFilter,
    setEventSearch,
    handleRefresh,
    handleDeleteInput,
    handleConnectGmail,
  };
}

function readApiDetailMessage(error: unknown): string | null {
  if (!(error instanceof ApiError)) {
    return null;
  }
  if (!error.body || typeof error.body !== "object") {
    return null;
  }
  const detail = (error.body as Record<string, unknown>).detail;
  if (!detail || typeof detail !== "object") {
    return null;
  }
  const message = (detail as Record<string, unknown>).message;
  return typeof message === "string" && message.trim() ? message : null;
}
