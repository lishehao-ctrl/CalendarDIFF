import { apiRequest } from "@/lib/api/client";
import {
  AppConfig,
  InputSource,
  SourceKindLiteral,
  SourceProviderLiteral,
  OAuthSessionCreateRequest,
  OAuthSessionCreateResponse,
  SyncRequestCreateRequest,
  SyncRequestCreateResponse,
  SyncRequestStatusResponse,
} from "@/lib/types";

export function getInputSources(config: AppConfig): Promise<InputSource[]> {
  return apiRequest<InputSource[]>(config, "/v2/input-sources", {}, "input");
}

export function createInputSource(
  config: AppConfig,
  payload: {
    source_kind: SourceKindLiteral;
    provider: SourceProviderLiteral | string;
    source_key?: string | null;
    display_name?: string | null;
    poll_interval_seconds?: number;
    config?: Record<string, unknown>;
    secrets?: Record<string, unknown>;
  },
): Promise<InputSource> {
  return apiRequest<InputSource>(config, "/v2/input-sources", {
    method: "POST",
    body: JSON.stringify(payload),
  }, "input");
}

export function createOAuthSession(
  config: AppConfig,
  payload: OAuthSessionCreateRequest,
): Promise<OAuthSessionCreateResponse> {
  return apiRequest<OAuthSessionCreateResponse>(config, "/v2/oauth-sessions", {
    method: "POST",
    body: JSON.stringify(payload),
  }, "input");
}

export function deleteInputSource(config: AppConfig, sourceId: number): Promise<{ deleted: boolean }> {
  return apiRequest<{ deleted: boolean }>(config, `/v2/input-sources/${sourceId}`, {
    method: "DELETE",
  }, "input");
}

export function createSyncRequest(
  config: AppConfig,
  payload: SyncRequestCreateRequest,
  idempotencyKey?: string,
): Promise<SyncRequestCreateResponse> {
  return apiRequest<SyncRequestCreateResponse>(config, "/v2/sync-requests", {
    method: "POST",
    body: JSON.stringify(payload),
    headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
  }, "input");
}

export function getSyncRequestStatus(config: AppConfig, requestId: string): Promise<SyncRequestStatusResponse> {
  return apiRequest<SyncRequestStatusResponse>(config, `/v2/sync-requests/${encodeURIComponent(requestId)}`, {}, "input");
}
