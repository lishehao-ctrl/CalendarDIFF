import { apiRequest } from "@/lib/api/client";
import {
  AppConfig,
  EmailQueueItem,
  MarkEmailViewedResponse,
  UpdateEmailRouteRequest,
  UpdateEmailRouteResponse,
} from "@/lib/types";

export function getEmailReviewQueue(
  config: AppConfig,
  params: {
    route?: "drop" | "archive" | "review";
    limit?: number;
    cursor?: string | null;
  } = {}
): Promise<EmailQueueItem[]> {
  const search = new URLSearchParams();
  if (params.route) {
    search.set("route", params.route);
  }
  if (typeof params.limit === "number") {
    search.set("limit", String(params.limit));
  }
  if (params.cursor) {
    search.set("cursor", params.cursor);
  }
  const query = search.toString();
  return apiRequest<EmailQueueItem[]>(config, `/v2/review-items/emails${query ? `?${query}` : ""}`);
}

export function updateEmailRoute(
  config: AppConfig,
  emailId: string,
  payload: UpdateEmailRouteRequest
): Promise<UpdateEmailRouteResponse> {
  return apiRequest<UpdateEmailRouteResponse>(config, `/v2/review-items/emails/${encodeURIComponent(emailId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function markEmailViewed(config: AppConfig, emailId: string): Promise<MarkEmailViewedResponse> {
  return apiRequest<MarkEmailViewedResponse>(config, `/v2/review-items/emails/${encodeURIComponent(emailId)}/views`, {
    method: "POST",
  });
}
