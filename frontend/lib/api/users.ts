import { apiRequest } from "@/lib/api/client";
import { AppConfig, DashboardUser } from "@/lib/types";

export type UserPatchRequest = {
  email?: string | null;
  notify_email?: string | null;
  calendar_delay_seconds?: number | null;
};

export function getCurrentUser(config: AppConfig): Promise<DashboardUser> {
  return apiRequest<DashboardUser>(config, "/v2/users/me", {}, "input");
}

export function patchCurrentUser(config: AppConfig, payload: UserPatchRequest): Promise<DashboardUser> {
  return apiRequest<DashboardUser>(config, "/v2/users/me", {
    method: "PATCH",
    body: JSON.stringify(payload),
  }, "input");
}
