import { apiRequest } from "@/lib/api/client";
import { AppConfig, EventListItem } from "@/lib/types";

export function getEvents(
  config: AppConfig,
  params: {
    input_id?: number;
    input_type?: "ics" | "email";
    q?: string;
    limit?: number;
    offset?: number;
  } = {}
): Promise<EventListItem[]> {
  const search = new URLSearchParams();
  if (typeof params.input_id === "number") {
    search.set("input_id", String(params.input_id));
  }
  if (params.input_type) {
    search.set("input_type", params.input_type);
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
  return apiRequest<EventListItem[]>(config, `/v1/events${query ? `?${query}` : ""}`);
}
