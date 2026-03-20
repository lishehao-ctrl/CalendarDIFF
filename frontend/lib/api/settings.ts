import { apiGet, apiPatch } from "@/lib/api/client";
import type { UserProfile } from "@/lib/types";

export async function getSettingsProfile() {
  return apiGet<UserProfile>("/settings/profile");
}

export async function updateSettingsProfile(payload: {
  email?: string | null;
  timezone_name?: string | null;
  timezone_source?: string | null;
  notify_email?: string | null;
  calendar_delay_seconds?: number | null;
}) {
  return apiPatch<UserProfile>("/settings/profile", payload);
}
