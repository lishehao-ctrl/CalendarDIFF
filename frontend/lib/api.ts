import {
  ApplyEmailReviewRequest,
  ApplyEmailReviewResponse,
  AppConfig,
  EvidencePreviewResponse,
  EmailQueueItem,
  MarkEmailViewedResponse,
  OnboardingRegisterRequest,
  OnboardingRegisterResponse,
  OnboardingStatus,
  UpdateEmailRouteRequest,
  UpdateEmailRouteResponse,
} from "@/lib/types";

const HOP_BY_HOP = new Set(["connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade"]);

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown = null) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export async function apiRequest<T>(config: AppConfig, path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers ?? {});
  headers.set("X-API-Key", config.apiKey);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${config.apiBase}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    const text = await response.text();
    const body = parseErrorBody(text);
    throw new ApiError(response.status, buildErrorMessage(response.status, response.statusText, text, body), body);
  }

  if (response.status === 204) {
    return null as T;
  }

  return (await response.json()) as T;
}

export function getOnboardingStatus(config: AppConfig): Promise<OnboardingStatus> {
  return apiRequest<OnboardingStatus>(config, "/v1/onboarding/status");
}

export function registerOnboarding(
  config: AppConfig,
  payload: OnboardingRegisterRequest,
): Promise<OnboardingRegisterResponse> {
  return apiRequest<OnboardingRegisterResponse>(config, "/v1/onboarding/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getEmailQueue(
  config: AppConfig,
  params: {
    route?: "drop" | "archive" | "notify" | "review";
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
  return apiRequest<EmailQueueItem[]>(config, `/v1/emails/queue${query ? `?${query}` : ""}`);
}

export function updateEmailRoute(
  config: AppConfig,
  emailId: string,
  payload: UpdateEmailRouteRequest
): Promise<UpdateEmailRouteResponse> {
  return apiRequest<UpdateEmailRouteResponse>(config, `/v1/emails/${encodeURIComponent(emailId)}/route`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function markEmailViewed(config: AppConfig, emailId: string): Promise<MarkEmailViewedResponse> {
  return apiRequest<MarkEmailViewedResponse>(config, `/v1/emails/${encodeURIComponent(emailId)}/mark_viewed`, {
    method: "POST",
  });
}

export function applyEmailReview(
  config: AppConfig,
  emailId: string,
  payload: ApplyEmailReviewRequest = {}
): Promise<ApplyEmailReviewResponse> {
  return apiRequest<ApplyEmailReviewResponse>(config, `/v1/emails/${encodeURIComponent(emailId)}/apply`, {
    method: "POST",
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
    `/v1/changes/${changeId}/evidence/${side}/preview`
  );
}

export function sanitizeHeaderMap(input: Headers): Headers {
  const output = new Headers();
  input.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) {
      output.set(key, value);
    }
  });
  return output;
}

function parseErrorBody(text: string): unknown {
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function buildErrorMessage(status: number, statusText: string, text: string, body: unknown): string {
  const detail = readDetailMessage(body);
  if (detail) {
    return `${status} ${statusText} - ${detail}`;
  }
  return `${status} ${statusText} - ${text}`;
}

function readDetailMessage(body: unknown): string | null {
  if (!body || typeof body !== "object") {
    return null;
  }
  const detail = (body as Record<string, unknown>).detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (detail && typeof detail === "object") {
    const message = (detail as Record<string, unknown>).message;
    if (typeof message === "string" && message.trim()) {
      return message;
    }
  }
  return null;
}
