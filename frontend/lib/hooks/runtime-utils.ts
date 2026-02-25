import { ApiError, apiRequest } from "@/lib/api";
import { ToastTone } from "@/lib/hooks/use-toast";
import { AppConfig, ManualSyncResponse, SourceBusyDetail } from "@/lib/types";

export const MIN_MANUAL_SYNC_ANIMATION_MS = 800;
export const MANUAL_SYNC_BUSY_RETRY_SECONDS = 10;

export type ManualSyncRequestResult =
  | { kind: "success"; result: ManualSyncResponse }
  | { kind: "busy"; detail: SourceBusyDetail }
  | { kind: "error"; message: string };

export function toErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

export function isOnboardingRequiredError(error: unknown): boolean {
  if (!(error instanceof ApiError)) {
    return false;
  }
  if (error.status !== 404 && error.status !== 409) {
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
  const code = (detail as Record<string, unknown>).code;
  return code === "user_not_initialized" || code === "user_onboarding_incomplete";
}

export function parsePositiveInt(raw: string | null): number | null {
  if (!raw) {
    return null;
  }
  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    return null;
  }
  return parsed;
}

export function syncSelectionQuery(inputId: number | null): void {
  const url = new URL(window.location.href);
  if (inputId === null) {
    url.searchParams.delete("input_id");
  } else {
    url.searchParams.set("input_id", String(inputId));
  }
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

export function previewCacheKey(changeId: number, side: "before" | "after"): string {
  return `${changeId}:${side}`;
}

export function handleManualSyncResult(
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

export async function requestManualSync(config: AppConfig, inputId: number): Promise<ManualSyncRequestResult> {
  try {
    const result = await apiRequest<ManualSyncResponse>(config, `/v1/inputs/${inputId}/sync`, {
      method: "POST",
    });
    return { kind: "success", result };
  } catch (error) {
    const busy = readInputBusyDetail(error);
    if (busy) {
      return { kind: "busy", detail: busy };
    }
    return { kind: "error", message: toErrorMessage(error) };
  }
}

function readInputBusyDetail(error: unknown): SourceBusyDetail | null {
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
  if (code !== "input_busy") {
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
    code: "input_busy",
    message,
    retry_after_seconds: retryAfter,
    recoverable,
  };
}
