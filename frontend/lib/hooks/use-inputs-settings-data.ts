import { useEffect, useState } from "react";

import { ApiError, deleteInput, startGmailOAuth } from "@/lib/api";
import {
  isGmailReconnectErrorCode,
  isOnboardingRequiredError,
  parsePositiveInt,
  requestManualSync,
  syncSelectionQuery,
  toErrorMessage,
} from "@/lib/hooks/runtime-utils";
import { useAppRuntime } from "@/lib/hooks/use-app-runtime";
import { Input } from "@/lib/types";

export function useInputsSettingsData() {
  const runtime = useAppRuntime();
  const { config, ensureOnboarded, needsOnboarding, setNeedsOnboarding, pushToast, bootstrap, refreshBootstrap } = runtime;

  const [inputs, setInputs] = useState<Input[]>([]);
  const [inputsLoading, setInputsLoading] = useState(false);
  const [inputsError, setInputsError] = useState<string | null>(null);
  const [activeInputId, setActiveInputId] = useState<number | null>(null);

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
    if (!bootstrap) {
      return;
    }
    applyInputs(bootstrap.inputs);
  }, [bootstrap]);

  useEffect(() => {
    if (!config || oauthQueryHandled) {
      return;
    }
    const params = new URLSearchParams(window.location.search);
    const oauthStatus = params.get("gmail_oauth_status");
    const oauthInputId = parsePositiveInt(params.get("input_id"));
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
      oauthInputId ? `Gmail connected successfully (input-${oauthInputId})` : "Gmail connected successfully",
      "success"
    );
    if (oauthInputId === null) {
      clearOauthQuery();
      setOauthQueryHandled(true);
      return;
    }

    setActiveInputId(oauthInputId);
    void (async () => {
      const result = await requestManualSync(config, oauthInputId);
      if (result.kind === "success") {
        if (isGmailReconnectErrorCode(result.result.error_code)) {
          pushToast("Gmail authorization is invalid. Reconnect Gmail in Inputs.", "error");
        } else if (result.result.last_error) {
          pushToast(`Gmail connected, but initial sync failed: ${result.result.last_error}`, "error");
        } else if (result.result.changes_created > 0) {
          pushToast("Gmail synced. New items entered review queue.", "success");
        } else {
          pushToast("Gmail connected and synced. No new email changes yet.", "info");
        }
      } else if (result.kind === "busy") {
        pushToast("Gmail connected. Initial sync is already in progress.", "info");
      } else {
        pushToast(`Gmail connected, but initial sync failed: ${result.message}`, "error");
      }

      await loadInputs(config);
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
    syncSelectionQuery(activeInputId);
  }, [config, activeInputId]);

  function applyInputs(rows: Input[]) {
    setInputs(rows);
    const firstActive = rows.find((row) => row.is_active) ?? rows[0] ?? null;
    setActiveInputId((current) => {
      if (current && rows.some((row) => row.id === current)) {
        return current;
      }
      return firstActive?.id ?? null;
    });
  }

  async function boot(runtimeConfig: NonNullable<typeof config>) {
    const onboarded = await ensureOnboarded(runtimeConfig);
    if (!onboarded) {
      setInputs([]);
      setActiveInputId(null);
      return;
    }
    await loadInputs(runtimeConfig);
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
      const payload = await refreshBootstrap(runtimeConfig);
      applyInputs(payload?.inputs ?? []);
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

  async function handleRefresh() {
    if (!config) {
      return;
    }
    const onboarded = await ensureOnboarded(config);
    if (!onboarded) {
      return;
    }
    await loadInputs(config);
  }

  async function handleDeleteInput(inputId: number) {
    if (!config || deletingInputId !== null) {
      return;
    }
    setDeletingInputId(inputId);
    try {
      await deleteInput(config, inputId);
      pushToast(`Input input-${inputId} deactivated`, "success");
      await loadInputs(config);
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
      pushToast(`Gmail OAuth start failed: ${toErrorMessage(error)}. Check OAuth config and retry.`, "error");
      setConnectingGmail(false);
    }
  }

  return {
    ...runtime,
    inputs,
    inputsLoading,
    inputsError,
    activeInputId,
    deletingInputId,
    connectingGmail,
    setActiveInputId,
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
