import { apiRequest } from "@/lib/api/client";
import { AppConfig, EventListItem } from "@/lib/types";

export function getEvents(
  config: AppConfig,
  params: {
    source_id?: number;
    source_kind?: "calendar" | "email";
    q?: string;
    limit?: number;
    offset?: number;
  } = {}
): Promise<EventListItem[]> {
  const search = new URLSearchParams();
  if (typeof params.source_id === "number") {
    search.set("source_id", String(params.source_id));
  }
  if (params.source_kind) {
    search.set("source_kind", params.source_kind);
  }
  if (params.q && params.q.trim()) {
    search.set("q", params.q.trim());
  }
  if (typeof params.limit === "number") {
    search.set("limit", String(params.limit));
  }
  if (typeof params.offset === "number") {
    search.set("offset", String(params.offset));
  }
  const query = search.toString();
  return apiRequest<EventListItem[]>(config, `/v2/timeline-events${query ? `?${query}` : ""}`);
}
