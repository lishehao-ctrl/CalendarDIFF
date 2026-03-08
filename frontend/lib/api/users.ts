import { apiGet, apiPatch } from "@/lib/api/client";
import type { UserProfile } from "@/lib/types";

export async function getCurrentUser() {
  return apiGet<UserProfile>("/users/me");
}

export async function updateCurrentUser(payload: { timezone_name?: string | null; notify_email?: string | null }) {
  return apiPatch<UserProfile>("/users/me", payload);
}
