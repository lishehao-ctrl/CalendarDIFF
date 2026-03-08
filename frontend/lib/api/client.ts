import { backendFetch } from "@/lib/backend";

export function buildQuery(params: Record<string, string | number | boolean | null | undefined>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") {
      continue;
    }
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export async function apiGet<T>(path: string): Promise<T> {
  return backendFetch<T>(path);
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return backendFetch<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body)
  });
}

export async function apiPatch<T>(path: string, body?: unknown): Promise<T> {
  return backendFetch<T>(path, {
    method: "PATCH",
    body: body === undefined ? undefined : JSON.stringify(body)
  });
}

export async function apiDelete<T>(path: string): Promise<T> {
  return backendFetch<T>(path, { method: "DELETE" });
}
