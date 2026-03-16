export async function backendFetch<T>(path: string, init?: RequestInit): Promise<T> {
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
      if (path.startsWith("/review/changes")) {
        return "Finish onboarding before opening the review inbox.";
      }
      if (path.startsWith("/review/links") || path.startsWith("/review/link")) {
        return "Finish onboarding before opening the family workspace.";
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
