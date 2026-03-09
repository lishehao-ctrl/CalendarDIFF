import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api/client";
import type { UserProfile, WorkItemKindMapping, WorkItemKindMappingStatus } from "@/lib/types";

export async function getCurrentUser() {
  return apiGet<UserProfile>("/users/me");
}

export async function updateCurrentUser(payload: { timezone_name?: string | null; notify_email?: string | null }) {
  return apiPatch<UserProfile>("/users/me", payload);
}


export async function listWorkItemKindMappings() {
  return apiGet<WorkItemKindMapping[]>("/users/me/work-item-kind-mappings");
}

export async function createWorkItemKindMapping(payload: { name: string; aliases: string[] }) {
  return apiPost<WorkItemKindMapping>("/users/me/work-item-kind-mappings", payload);
}

export async function updateWorkItemKindMapping(mappingId: number, payload: { name: string; aliases: string[] }) {
  return apiPatch<WorkItemKindMapping>(`/users/me/work-item-kind-mappings/${mappingId}`, payload);
}

export async function deleteWorkItemKindMapping(mappingId: number) {
  return apiDelete<{ deleted: boolean }>(`/users/me/work-item-kind-mappings/${mappingId}`);
}

export async function getWorkItemKindMappingStatus() {
  return apiGet<WorkItemKindMappingStatus>("/users/me/work-item-kind-mappings/status");
}
