import { apiGet, apiPost } from "@/lib/api/client";
import { getBrowserTimeZone } from "@/lib/browser-timezone";

export async function login(payload: { notify_email: string; password: string }) {
  return apiPost("/auth/login", { ...payload, timezone_name: getBrowserTimeZone() });
}

export async function register(payload: { notify_email: string; password: string }) {
  return apiPost("/auth/register", { ...payload, timezone_name: getBrowserTimeZone() });
}

export async function logout() {
  return apiPost<{ logged_out: boolean }>("/auth/logout");
}

export async function getSession() {
  return apiGet("/auth/session");
}
