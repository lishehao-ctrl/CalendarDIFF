import { ApiError, createSyncRequest, getSyncRequestStatus } from "@/lib/api";
import { ToastTone } from "@/lib/hooks/use-toast";
import { AppConfig, SyncRequestStatusResponse } from "@/lib/types";

export const MIN_MANUAL_SYNC_ANIMATION_MS = 800;
export const SYNC_REQUEST_POLL_INTERVAL_MS = 1500;
export const SYNC_REQUEST_POLL_TIMEOUT_MS = 90_000;

export type ManualSyncRequestResult =
  | { kind: "success"; result: SyncRequestStatusResponse }
  | { kind: "error"; message: string };

const GMAIL_RECONNECT_ERROR_CODES = new Set([
  "gmail_missing_access_token",
  "gmail_auth_failed",
  "fetch_gmail_auth_missing_access_token",
  "fetch_gmail_auth_refresh_token_missing",
  "fetch_gmail_auth_refresh_failed",
]);

const TERMINAL_SYNC_REQUEST_STATUSES = new Set(["SUCCEEDED", "FAILED"]);

export function isGmailReconnectErrorCode(code: string | null | undefined): boolean {
  return typeof code === "string" && GMAIL_RECONNECT_ERROR_CODES.has(code);
}

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

export function syncSelectionQuery(sourceId: number | null): void {
  const url = new URL(window.location.href);
  if (sourceId === null) {
    url.searchParams.delete("source_id");
  } else {
    url.searchParams.set("source_id", String(sourceId));
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
  result: SyncRequestStatusResponse,
  pushToast: (message: string, tone: ToastTone) => void,
): void {
  if (isGmailReconnectErrorCode(result.error_code ?? result.connector_result?.error_code)) {
    pushToast("Gmail authorization is invalid. Reconnect Gmail in Sources.", "error");
    return;
  }

  if (result.status === "FAILED") {
    pushToast(`Sync failed: ${result.error_message ?? result.connector_result?.error_message ?? "unknown error"}`, "error");
    return;
  }

  const connectorStatus = result.connector_result?.status;
  if (connectorStatus === "NO_CHANGE") {
    pushToast("Checked just now - no changes", "info");
    return;
  }
  if (connectorStatus === "CHANGED") {
    pushToast("Sync completed - new source data ingested", "success");
    return;
  }
  pushToast("Sync completed", "success");
}

export async function requestManualSync(config: AppConfig, sourceId: number): Promise<ManualSyncRequestResult> {
  try {
    const created = await createSyncRequest(config, { source_id: sourceId });
    const result = await waitForSyncRequestTerminal(config, created.request_id);
    return { kind: "success", result };
  } catch (error) {
    return { kind: "error", message: toErrorMessage(error) };
  }
}

async function waitForSyncRequestTerminal(
  config: AppConfig,
  requestId: string,
  timeoutMs = SYNC_REQUEST_POLL_TIMEOUT_MS,
): Promise<SyncRequestStatusResponse> {
  const deadline = Date.now() + timeoutMs;
  let latest = await getSyncRequestStatus(config, requestId);
  while (!TERMINAL_SYNC_REQUEST_STATUSES.has(latest.status)) {
    if (Date.now() >= deadline) {
      throw new Error("sync request timed out before reaching terminal state");
    }
    await sleep(SYNC_REQUEST_POLL_INTERVAL_MS);
    latest = await getSyncRequestStatus(config, requestId);
  }
  return latest;
}
