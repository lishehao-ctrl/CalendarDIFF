import {
  AppConfig,
  OnboardingRegisterRequest,
  OnboardingRegisterResponse,
  OnboardingStatus,
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

export async function downloadEvidence(
  config: AppConfig,
  inputId: number,
  changeId: number,
  side: "before" | "after"
): Promise<void> {
  const response = await fetch(`${config.apiBase}/v1/inputs/${inputId}/changes/${changeId}/evidence/${side}/download`, {
    method: "GET",
    headers: {
      "X-API-Key": config.apiKey,
    },
  });

  if (!response.ok) {
    const text = await response.text();
    const body = parseErrorBody(text);
    throw new ApiError(response.status, buildErrorMessage(response.status, response.statusText, text, body), body);
  }

  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const fallback = `change-${changeId}-${side}.ics`;
  const filename = parseDownloadFilename(disposition, fallback);
  const objectUrl = window.URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
  } finally {
    window.URL.revokeObjectURL(objectUrl);
  }
}

function parseDownloadFilename(contentDisposition: string, fallback: string): string {
  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    return decodeURIComponent(utf8Match[1]);
  }

  const simpleMatch = contentDisposition.match(/filename=\"?([^\";]+)\"?/i);
  if (simpleMatch?.[1]) {
    return simpleMatch[1];
  }

  return fallback;
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
