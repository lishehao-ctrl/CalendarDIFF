import { apiRequest } from "@/lib/api/client";
import {
  AppConfig,
  ChangeFeedRecord,
  EvidencePreviewResponse,
  ChangeRecord,
} from "@/lib/types";

export function getFeed(
  config: AppConfig,
  params: {
    source_kinds?: "calendar" | "email";
    limit?: number;
    offset?: number;
    view?: "all" | "unread";
  } = {}
): Promise<ChangeFeedRecord[]> {
  const search = new URLSearchParams();
  if (params.source_kinds) {
    search.set("source_kinds", params.source_kinds);
  }
  if (typeof params.limit === "number") {
    search.set("limit", String(params.limit));
  }
  if (typeof params.offset === "number") {
    search.set("offset", String(params.offset));
  }
  if (params.view) {
    search.set("view", params.view);
  }
  const query = search.toString();
  return apiRequest<ChangeFeedRecord[]>(config, `/v2/change-events${query ? `?${query}` : ""}`);
}

export function patchChangeViewed(
  config: AppConfig,
  changeId: number,
  payload: {
    viewed: boolean;
    note?: string | null;
  }
): Promise<ChangeRecord> {
  return apiRequest<ChangeRecord>(config, `/v2/change-events/${changeId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function getEvidencePreview(
  config: AppConfig,
  changeId: number,
  side: "before" | "after"
): Promise<EvidencePreviewResponse> {
  return apiRequest<EvidencePreviewResponse>(
    config,
    `/v2/change-events/${changeId}/evidence/${side}/preview`
  );
}
