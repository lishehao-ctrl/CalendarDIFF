import { apiRequest } from "@/lib/api/client";
import {
  AppConfig,
  ApplyEmailReviewRequest,
  ApplyEmailReviewResponse,
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
  return apiRequest<EmailQueueItem[]>(config, `/v1/review/emails${query ? `?${query}` : ""}`);
}

export function updateEmailRoute(
  config: AppConfig,
  emailId: string,
  payload: UpdateEmailRouteRequest
): Promise<UpdateEmailRouteResponse> {
  return apiRequest<UpdateEmailRouteResponse>(config, `/v1/review/emails/${encodeURIComponent(emailId)}/route`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function markEmailViewed(config: AppConfig, emailId: string): Promise<MarkEmailViewedResponse> {
  return apiRequest<MarkEmailViewedResponse>(config, `/v1/review/emails/${encodeURIComponent(emailId)}/viewed`, {
    method: "POST",
  });
}

export function applyEmailReview(
  config: AppConfig,
  emailId: string,
  payload: ApplyEmailReviewRequest = {}
): Promise<ApplyEmailReviewResponse> {
  return apiRequest<ApplyEmailReviewResponse>(config, `/v1/review/emails/${encodeURIComponent(emailId)}/apply`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
