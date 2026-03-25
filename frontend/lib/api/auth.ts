import { apiGet, apiPost } from "@/lib/api/client";
import { getBrowserTimeZone } from "@/lib/browser-timezone";

export async function login(payload: { email: string; password: string; language_code?: "en" | "zh-CN" }) {
  return apiPost("/auth/login", { ...payload, timezone_name: getBrowserTimeZone() });
}

export async function register(payload: { email: string; password: string; language_code?: "en" | "zh-CN" }) {
  return apiPost("/auth/register", { ...payload, timezone_name: getBrowserTimeZone() });
}

export async function logout() {
  return apiPost<{ logged_out: boolean }>("/auth/logout");
}

export async function getSession() {
  return apiGet("/auth/session");
}
