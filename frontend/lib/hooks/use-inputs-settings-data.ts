import { useEffect, useState } from "react";

import { ApiError, createInputSource, createOAuthSession, deleteInputSource } from "@/lib/api";
import {
  handleManualSyncResult,
  isOnboardingRequiredError,
  parsePositiveInt,
  requestManualSync,
  syncSelectionQuery,
  toErrorMessage,
} from "@/lib/hooks/runtime-utils";
import { useAppRuntime } from "@/lib/hooks/use-app-runtime";
import { InputSource } from "@/lib/types";

export function useInputsSettingsData() {
  const runtime = useAppRuntime();
  const { config, ensureOnboarded, needsOnboarding, setNeedsOnboarding, pushToast, sources, refreshRuntime } = runtime;

  const [sourceRows, setSourceRows] = useState<InputSource[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [sourcesError, setSourcesError] = useState<string | null>(null);
  const [activeSourceId, setActiveSourceId] = useState<number | null>(null);

  const [deletingSourceId, setDeletingSourceId] = useState<number | null>(null);
  const [connectingGmail, setConnectingGmail] = useState(false);
  const [oauthQueryHandled, setOauthQueryHandled] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sourceId = parsePositiveInt(params.get("source_id"));
    if (sourceId !== null) {
      setActiveSourceId(sourceId);
    }
  }, []);

  useEffect(() => {
    applySources(sourceRowsFromRuntime(sources));
  }, [sources]);

  useEffect(() => {
    if (!config || oauthQueryHandled) {
      return;
    }
    const params = new URLSearchParams(window.location.search);
    const oauthStatus = params.get("gmail_oauth_status");
    const oauthSourceId = parsePositiveInt(params.get("source_id"));
    const oauthMessage = params.get("message");

    const clearOauthQuery = () => {
      params.delete("gmail_oauth_status");
      params.delete("message");
      const query = params.toString();
      window.history.replaceState({}, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
    };

    if (oauthStatus === "error") {
      const detail = oauthMessage?.trim() ? oauthMessage.trim() : "Unknown error";
      pushToast(`Gmail connect failed: ${detail}. Reconnect Gmail and try again.`, "error");
      clearOauthQuery();
      setOauthQueryHandled(true);
      return;
    }

    if (oauthStatus !== "success") {
      setOauthQueryHandled(true);
      return;
    }

    pushToast(
      oauthSourceId ? `Gmail connected successfully (source-${oauthSourceId})` : "Gmail connected successfully",
      "success"
    );
    if (oauthSourceId === null) {
      clearOauthQuery();
      setOauthQueryHandled(true);
      return;
    }

    setActiveSourceId(oauthSourceId);
    void (async () => {
      const result = await requestManualSync(config, oauthSourceId);
      if (result.kind === "success") {
        handleManualSyncResult(result.result, pushToast);
      } else {
        pushToast(`Gmail connected, but initial sync failed: ${result.message}`, "error");
      }
      await loadSources(config);
      clearOauthQuery();
      setOauthQueryHandled(true);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    syncSelectionQuery(activeSourceId);
  }, [config, activeSourceId]);

  function applySources(rows: InputSource[]) {
    setSourceRows(rows);
    const firstActive = rows.find((row) => row.is_active) ?? rows[0] ?? null;
    setActiveSourceId((current) => {
      if (current && rows.some((row) => row.source_id === current)) {
        return current;
      }
      return firstActive?.source_id ?? null;
    });
  }

  async function boot(runtimeConfig: NonNullable<typeof config>) {
    const onboarded = await ensureOnboarded(runtimeConfig);
    if (!onboarded) {
      setSourceRows([]);
      setActiveSourceId(null);
      return;
    }
    await loadSources(runtimeConfig);
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
      applySources(sourceRowsFromRuntime(snapshot?.sources ?? []));
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

  async function handleRefresh() {
    if (!config) {
      return;
    }
    const onboarded = await ensureOnboarded(config);
    if (!onboarded) {
      return;
    }
    await loadSources(config);
  }

  async function handleDeleteSource(sourceId: number) {
    if (!config || deletingSourceId !== null) {
      return;
    }
    setDeletingSourceId(sourceId);
    try {
      await deleteInputSource(config, sourceId);
      pushToast(`Source source-${sourceId} deactivated`, "success");
      await loadSources(config);
    } catch (error) {
      const inactiveDetail = readApiDetailMessage(error);
      pushToast(inactiveDetail ?? toErrorMessage(error), "error");
    } finally {
      setDeletingSourceId(null);
    }
  }

  async function handleConnectGmail() {
    if (!config || connectingGmail) {
      return;
    }
    setConnectingGmail(true);
    try {
      const source = await createInputSource(config, {
        source_kind: "email",
        provider: "gmail",
        display_name: null,
        config: {},
        secrets: {},
      });
      const oauth = await createOAuthSession(config, {
        source_id: source.source_id,
        provider: "gmail",
      });
      window.location.assign(oauth.authorization_url);
    } catch (error) {
      pushToast(`Gmail OAuth start failed: ${toErrorMessage(error)}. Check OAuth config and retry.`, "error");
      setConnectingGmail(false);
    }
  }

  return {
    ...runtime,
    sourceRows,
    sourcesLoading,
    sourcesError,
    activeSourceId,
    deletingSourceId,
    connectingGmail,
    setActiveSourceId,
    handleRefresh,
    handleDeleteSource,
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

function sourceRowsFromRuntime(rows: InputSource[]): InputSource[] {
  return rows.slice().sort((a, b) => a.source_id - b.source_id);
}
