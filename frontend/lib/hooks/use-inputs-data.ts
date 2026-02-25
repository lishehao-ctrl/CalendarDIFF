import { FormEvent, useEffect, useState } from "react";

import { apiRequest } from "@/lib/api";
import { isOnboardingRequiredError, parsePositiveInt, syncSelectionQuery, toErrorMessage } from "@/lib/hooks/runtime-utils";
import { useAppRuntime } from "@/lib/hooks/use-app-runtime";
import { GmailOAuthStartRequest, GmailOAuthStartResponse, Input } from "@/lib/types";

export function useInputsData() {
  const runtime = useAppRuntime();
  const { config, ensureOnboarded, pushToast, needsOnboarding, setNeedsOnboarding } = runtime;

  const [activeInputId, setActiveInputId] = useState<number | null>(null);
  const [sourceEmailLabel, setSourceEmailLabel] = useState("");
  const [sourceEmailFromContains, setSourceEmailFromContains] = useState("");
  const [sourceEmailSubjectKeywords, setSourceEmailSubjectKeywords] = useState("");
  const [createBusy, setCreateBusy] = useState(false);

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
    void (async () => {
      const onboarded = await ensureOnboarded(config);
      if (!onboarded) {
        return;
      }
      await loadInputs(config);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config]);

  useEffect(() => {
    if (!config) {
      return;
    }
    syncSelectionQuery(activeInputId);
  }, [config, activeInputId]);

  useEffect(() => {
    if (!config) {
      return;
    }
    const params = new URLSearchParams(window.location.search);
    const oauthStatus = params.get("gmail_oauth_status");
    if (!oauthStatus) {
      return;
    }

    const inputIdParam = params.get("input_id");
    const message = params.get("message");

    if (oauthStatus === "success") {
      pushToast("Gmail connected successfully", "success");
      const parsed = parsePositiveInt(inputIdParam);
      if (parsed !== null) {
        setActiveInputId(parsed);
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
      const onboarded = await ensureOnboarded(config);
      if (!onboarded) {
        return;
      }
      await loadInputs(config);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config]);

  async function loadInputs(runtimeConfig = config): Promise<void> {
    if (!runtimeConfig) {
      return;
    }
    if (needsOnboarding) {
      return;
    }

    try {
      const rows = await apiRequest<Input[]>(runtimeConfig, "/v1/inputs");
      if (rows.length === 0) {
        setActiveInputId(null);
        return;
      }
      setActiveInputId((current) => {
        if (current && rows.some((item) => item.id === current)) {
          return current;
        }
        return rows[0].id;
      });
    } catch (error) {
      if (isOnboardingRequiredError(error)) {
        setNeedsOnboarding(true);
      }
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

  return {
    ...runtime,
    activeSourceId: activeInputId,
    sourceEmailLabel,
    sourceEmailFromContains,
    sourceEmailSubjectKeywords,
    setSourceEmailLabel,
    setSourceEmailFromContains,
    setSourceEmailSubjectKeywords,
    createBusy,
    handleConnectGmailInput,
  };
}
