import { apiDelete, apiGet, apiPatch, apiPost, buildQuery } from "@/lib/api/client";
import type { ManualEvent, ManualEventMutationResponse } from "@/lib/types";

export async function listManualEvents(params?: { include_removed?: boolean }) {
  return apiGet<ManualEvent[]>(`/manual/events${buildQuery(params || {})}`);
}

export async function createManualEvent(payload: {
  family_id: number;
  event_name: string;
  raw_type?: string | null;
  ordinal?: number | null;
  due_date: string;
  due_time?: string | null;
  time_precision: "date_only" | "datetime";
  reason?: string | null;
}) {
  return apiPost<ManualEventMutationResponse>("/manual/events", payload);
}

export async function updateManualEvent(
  entityUid: string,
  payload: {
    family_id: number;
    event_name: string;
    raw_type?: string | null;
    ordinal?: number | null;
    due_date: string;
    due_time?: string | null;
    time_precision: "date_only" | "datetime";
    reason?: string | null;
  },
) {
  return apiPatch<ManualEventMutationResponse>(`/manual/events/${encodeURIComponent(entityUid)}`, payload);
}

export async function deleteManualEvent(entityUid: string, reason?: string | null) {
  const query = buildQuery({ reason: reason || undefined });
  return apiDelete<ManualEventMutationResponse>(`/manual/events/${encodeURIComponent(entityUid)}${query}`);
}
