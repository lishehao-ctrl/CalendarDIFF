import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api/client";
import type { McpAccessToken, McpAccessTokenCreateResponse, UserProfile } from "@/lib/types";

export function settingsProfileCacheKey() {
  return "settings:profile";
}

export function settingsMcpTokensCacheKey() {
  return "settings:mcp-tokens";
}

export async function getSettingsProfile() {
  return apiGet<UserProfile>("/settings/profile");
}

export async function updateSettingsProfile(payload: {
  language_code?: "en" | "zh-CN" | null;
  timezone_name?: string | null;
  timezone_source?: string | null;
  calendar_delay_seconds?: number | null;
}) {
  return apiPatch<UserProfile>("/settings/profile", payload);
}

export async function getMcpTokens() {
  return apiGet<McpAccessToken[]>("/settings/mcp-tokens");
}

export async function createMcpToken(payload: {
  label: string;
  expires_in_days: number;
}) {
  return apiPost<McpAccessTokenCreateResponse>("/settings/mcp-tokens", payload);
}

export async function revokeMcpToken(tokenId: string) {
  return apiDelete<McpAccessToken>(`/settings/mcp-tokens/${encodeURIComponent(tokenId)}`);
}
