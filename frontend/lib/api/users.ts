import { apiGet, apiPatch, apiPost, buildQuery } from "@/lib/api/client";
import type { CourseIdentity, CourseWorkItemFamily, CourseWorkItemFamilyStatus, UserProfile } from "@/lib/types";

export async function getCurrentUser() {
  return apiGet<UserProfile>("/users/me");
}

export async function updateCurrentUser(payload: { timezone_name?: string | null; timezone_source?: string | null; notify_email?: string | null }) {
  return apiPatch<UserProfile>("/users/me", payload);
}

export async function listCourseWorkItemFamilies(params?: {
  course_dept?: string | null;
  course_number?: number | null;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
}) {
  return apiGet<CourseWorkItemFamily[]>(`/users/me/course-work-item-families${buildQuery(params || {})}`);
}

export async function createCourseWorkItemFamily(payload: {
  course_dept: string;
  course_number: number;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
  canonical_label: string;
  raw_types: string[];
}) {
  return apiPost<CourseWorkItemFamily>("/users/me/course-work-item-families", payload);
}

export async function updateCourseWorkItemFamily(familyId: number, payload: {
  course_dept: string;
  course_number: number;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
  canonical_label: string;
  raw_types: string[];
}) {
  return apiPatch<CourseWorkItemFamily>(`/users/me/course-work-item-families/${familyId}`, payload);
}

export async function getCourseWorkItemFamilyStatus() {
  return apiGet<CourseWorkItemFamilyStatus>("/users/me/course-work-item-families/status");
}

export async function listKnownCourseKeys() {
  return apiGet<{ courses: CourseIdentity[] }>("/users/me/course-work-item-families/courses");
}
