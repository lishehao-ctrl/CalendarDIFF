import { apiDelete, apiGet, apiPatch, apiPost, buildQuery } from "@/lib/api/client";
import type {
  SourceObservabilityResponse,
  SourceRow,
  SourceSyncHistoryResponse,
  SyncStatus,
} from "@/lib/types";

export function sourceListCacheKey(status: "active" | "archived" | "all" = "active") {
  return `sources:list${buildQuery({ status })}`;
}

export function sourceObservabilityCacheKey(sourceId: number) {
  return `sources:${sourceId}:observability`;
}

export function sourceSyncHistoryCacheKey(sourceId: number, limit?: number) {
  return `sources:${sourceId}:sync-history${buildQuery({ limit })}`;
}

export async function listSources(params?: { status?: "active" | "archived" | "all" }) {
  return apiGet<SourceRow[]>(`/sources${buildQuery({ status: params?.status || "active" })}`);
}

export async function createSource(payload: Record<string, unknown>) {
  return apiPost<SourceRow>("/sources", payload);
}

export async function updateSource(sourceId: number, payload: Record<string, unknown>) {
  return apiPatch<SourceRow>(`/sources/${sourceId}`, payload);
}

export async function deleteSource(sourceId: number) {
  return apiDelete<{ deleted: boolean }>(`/sources/${sourceId}`);
}

export async function createSyncRequest(sourceId: number, payload: Record<string, unknown>) {
  return apiPost<{ request_id: string }>(`/sources/${sourceId}/sync-requests`, payload);
}

export async function getSyncRequest(requestId: string) {
  return apiGet<SyncStatus>(`/sync-requests/${requestId}`);
}

export async function createOAuthSession(sourceId: number, payload: Record<string, unknown>) {
  return apiPost<{ authorization_url: string }>(`/sources/${sourceId}/oauth-sessions`, payload);
}

export async function getSourceObservability(sourceId: number) {
  return apiGet<SourceObservabilityResponse>(`/sources/${sourceId}/observability`);
}

export async function getSourceSyncHistory(sourceId: number, params?: { limit?: number }) {
  return apiGet<SourceSyncHistoryResponse>(`/sources/${sourceId}/sync-history${buildQuery({ limit: params?.limit })}`);
}
