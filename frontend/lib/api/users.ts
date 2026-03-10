import { apiDelete, apiGet, apiPatch, apiPost, buildQuery } from "@/lib/api/client";
import type { CourseWorkItemFamily, CourseWorkItemFamilyStatus, UserProfile } from "@/lib/types";

export async function getCurrentUser() {
  return apiGet<UserProfile>("/users/me");
}

export async function updateCurrentUser(payload: { timezone_name?: string | null; notify_email?: string | null }) {
  return apiPatch<UserProfile>("/users/me", payload);
}

export async function listCourseWorkItemFamilies(params?: { course_key?: string | null }) {
  return apiGet<CourseWorkItemFamily[]>(`/users/me/course-work-item-families${buildQuery({ course_key: params?.course_key })}`);
}

export async function createCourseWorkItemFamily(payload: { course_key: string; canonical_label: string; aliases: string[] }) {
  return apiPost<CourseWorkItemFamily>("/users/me/course-work-item-families", payload);
}

export async function updateCourseWorkItemFamily(familyId: number, payload: { course_key: string; canonical_label: string; aliases: string[] }) {
  return apiPatch<CourseWorkItemFamily>(`/users/me/course-work-item-families/${familyId}`, payload);
}

export async function deleteCourseWorkItemFamily(familyId: number) {
  return apiDelete<{ deleted: boolean }>(`/users/me/course-work-item-families/${familyId}`);
}

export async function getCourseWorkItemFamilyStatus(courseKey?: string | null) {
  return apiGet<CourseWorkItemFamilyStatus>(`/users/me/course-work-item-families/status${buildQuery({ course_key: courseKey })}`);
}

export async function listKnownCourseKeys() {
  return apiGet<{ courses: string[] }>("/users/me/course-work-item-families/courses");
}
