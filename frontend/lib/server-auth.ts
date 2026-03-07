import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

const SESSION_COOKIE_NAME = "calendardiff_session";

export type ServerSession = {
  authenticated: true;
  user: {
    id: number;
    notify_email: string;
    timezone_name: string;
    created_at: string;
    onboarding_stage: "needs_source_connection" | "ready";
    first_source_id: number | null;
  };
};

function normalizeBaseUrl(value: string | undefined) {
  return value?.trim().replace(/\/$/, "") || "";
}

export async function getServerSession(): Promise<ServerSession | null> {
  const inputBase = normalizeBaseUrl(process.env.INPUT_BACKEND_BASE_URL) || normalizeBaseUrl(process.env.BACKEND_BASE_URL);
  const apiKey = process.env.BACKEND_API_KEY?.trim();
  const cookieStore = cookies();
  const sessionCookie = cookieStore.get(SESSION_COOKIE_NAME)?.value;

  if (!inputBase || !apiKey || !sessionCookie) {
    return null;
  }

  const response = await fetch(`${inputBase}/auth/session`, {
    headers: {
      "X-API-Key": apiKey,
      Cookie: `${SESSION_COOKIE_NAME}=${sessionCookie}`,
      Accept: "application/json"
    },
    cache: "no-store"
  });

  if (response.status === 401) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Auth session fetch failed: ${response.status}`);
  }
  return (await response.json()) as ServerSession;
}

export async function requireServerSession(): Promise<ServerSession> {
  const session = await getServerSession();
  if (!session) {
    redirect("/login");
  }
  return session;
}
