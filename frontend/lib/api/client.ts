import { AppConfig } from "@/lib/types";

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
]);

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown = null) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export type ApiService = "input" | "review" | "ingest" | "notify";

export async function apiRequest<T>(
  config: AppConfig,
  path: string,
  init: RequestInit = {},
  service: ApiService = "review"
): Promise<T> {
  const headers = new Headers(init.headers ?? {});
  headers.set("X-API-Key", config.apiKey);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const base = resolveApiBase(config, service);

  const response = await fetch(`${base}${path}`, {
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

function resolveApiBase(config: AppConfig, service: ApiService): string {
  if (service === "input") {
    return config.inputApiBase ?? config.apiBase;
  }
  if (service === "ingest") {
    return config.ingestApiBase ?? config.apiBase;
  }
  if (service === "notify") {
    return config.notifyApiBase ?? config.apiBase;
  }
  return config.reviewApiBase ?? config.apiBase;
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
