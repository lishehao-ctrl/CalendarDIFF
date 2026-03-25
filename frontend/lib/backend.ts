import { demoBackendFetch } from "@/lib/demo-backend";
import { getClientPreviewMode } from "@/lib/demo-mode";

export async function backendFetch<T>(path: string, init?: RequestInit): Promise<T> {
  if (getClientPreviewMode()) {
    return demoBackendFetch<T>(path, init);
  }

  const response = await fetch(`/api/backend${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    },
    cache: "no-store"
  });

  if (response.status === 401) {
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login") && !window.location.pathname.startsWith("/register")) {
      window.location.assign("/login");
    }
  }

  if (!response.ok) {
    const body = await response.text();
    throw new Error(extractErrorMessage(path, response.status, body));
  }

  if (response.status === 204) {
    return null as T;
  }

  return (await response.json()) as T;
}

function extractErrorMessage(path: string, status: number, body: string) {
  const trimmed = body.trim();
  if (!trimmed) {
    return `Backend request failed: ${status}`;
  }

  try {
    const payload = JSON.parse(trimmed);
    return humanizeErrorPayload(path, status, payload);
  } catch {
    return trimmed;
  }
}

function humanizeErrorPayload(path: string, status: number, payload: unknown) {
  const detail =
    payload && typeof payload === "object" && "detail" in payload
      ? (payload as { detail?: unknown }).detail
      : payload;

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (!item || typeof item !== "object") return null;
        const entry = item as { loc?: unknown; msg?: unknown };
        const msg = typeof entry.msg === "string" ? entry.msg.trim() : "";
        if (!msg) return null;
        const loc = Array.isArray(entry.loc) ? entry.loc[entry.loc.length - 1] : null;
        return typeof loc === "string" && loc ? `${loc}: ${msg}` : msg;
      })
      .filter((value): value is string => Boolean(value));
    if (messages.length > 0) {
      return messages.join("; ");
    }
  }

  if (typeof detail === "string" && detail.trim()) {
    return detail.trim();
  }

  if (detail && typeof detail === "object") {
    const code = "code" in detail && typeof (detail as { code?: unknown }).code === "string"
      ? (detail as { code: string }).code
      : null;
    const message = "message" in detail && typeof (detail as { message?: unknown }).message === "string"
      ? (detail as { message: string }).message
      : null;

    if (code === "user_onboarding_incomplete") {
      if (message) {
        return message;
      }
      if (path.startsWith("/changes")) {
        return "Finish onboarding before opening Changes.";
      }
      if (path.startsWith("/sources")) {
        return "Finish onboarding before opening source posture.";
      }
      if (path.startsWith("/families")) {
        return "Finish onboarding before opening the family workspace.";
      }
      if (path.startsWith("/manual")) {
        return "Finish onboarding before opening the manual repair workspace.";
      }
      if (path.startsWith("/settings")) {
        return "Finish onboarding before opening Settings.";
      }
      return "Finish onboarding before continuing.";
    }

    if (code === "gmail_source_exists") {
      return "A Gmail mailbox is already connected for this workspace.";
    }
    if (code === "ics_source_exists") {
      return "A Canvas ICS link is already connected for this workspace.";
    }
    if (code === "source_inactive") {
      return "This source is archived. Reactivate it in Sources before syncing.";
    }

    if (message) {
      return message;
    }
  }

  if (status === 401) {
    return "Please sign in again.";
  }

  return trimmedFallback(payload, status);
}

function trimmedFallback(payload: unknown, status: number) {
  if (typeof payload === "string" && payload.trim()) {
    return payload.trim();
  }
  try {
    return JSON.stringify(payload);
  } catch {
    return `Backend request failed: ${status}`;
  }
}
