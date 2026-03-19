import { apiDelete, apiGet, apiPatch, apiPost, buildQuery } from "@/lib/api/client";
import type {
  CourseIdentity,
  CourseWorkItemRawType,
  CourseWorkItemRawTypeMoveResponse,
  CourseWorkItemFamily,
  CourseWorkItemFamilyStatus,
  ManualEvent,
  ManualEventMutationResponse,
  RawTypeSuggestionDecisionResponse,
  RawTypeSuggestionItem,
  UserProfile,
} from "@/lib/types";

export async function getCurrentUser() {
  return apiGet<UserProfile>("/profile/me");
}

export async function updateCurrentUser(payload: {
  timezone_name?: string | null;
  timezone_source?: string | null;
  notify_email?: string | null;
}) {
  return apiPatch<UserProfile>("/profile/me", payload);
}

export async function listCourseWorkItemFamilies(params?: {
  course_dept?: string | null;
  course_number?: number | null;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
}) {
  return apiGet<CourseWorkItemFamily[]>(`/review/course-work-item-families${buildQuery(params || {})}`);
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
  return apiPost<CourseWorkItemFamily>("/review/course-work-item-families", payload);
}

export async function updateCourseWorkItemFamily(
  familyId: number,
  payload: {
    course_dept: string;
    course_number: number;
    course_suffix?: string | null;
    course_quarter?: string | null;
    course_year2?: number | null;
    canonical_label: string;
    raw_types: string[];
  }
) {
  return apiPatch<CourseWorkItemFamily>(`/review/course-work-item-families/${familyId}`, payload);
}

export async function getCourseWorkItemFamilyStatus() {
  return apiGet<CourseWorkItemFamilyStatus>("/review/course-work-item-families/status");
}

export async function listKnownCourseKeys() {
  return apiGet<{ courses: CourseIdentity[] }>("/review/course-work-item-families/courses");
}

export async function listCourseWorkItemRawTypes(params?: {
  course_dept?: string | null;
  course_number?: number | null;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
  family_id?: number | null;
}) {
  return apiGet<CourseWorkItemRawType[]>(`/review/course-work-item-raw-types${buildQuery(params || {})}`);
}

export async function moveCourseRawTypeToFamily(payload: {
  raw_type_id: number;
  family_id: number;
  note?: string | null;
}) {
  return apiPost<CourseWorkItemRawTypeMoveResponse>("/review/course-work-item-raw-types/relink", payload);
}

export async function listRawTypeSuggestions(params?: {
  status?: "pending" | "approved" | "rejected" | "dismissed";
  course_dept?: string | null;
  course_number?: number | null;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
  limit?: number;
  offset?: number;
}) {
  return apiGet<RawTypeSuggestionItem[]>(`/review/raw-type-suggestions${buildQuery({ status: "pending", ...(params || {}) })}`);
}

export async function decideRawTypeSuggestion(
  suggestionId: number,
  payload: {
    decision: "approve" | "reject" | "dismiss";
    note?: string | null;
  }
) {
  return apiPost<RawTypeSuggestionDecisionResponse>(`/review/raw-type-suggestions/${suggestionId}/decisions`, payload);
}

export async function listManualEvents(params?: { include_removed?: boolean }) {
  return apiGet<ManualEvent[]>(`/events/manual${buildQuery(params || {})}`);
}

export async function createManualEvent(payload: {
  family_id: number;
  event_name: string;
  raw_type?: string | null;
  ordinal?: number | null;
  due_date: string;
  due_time?: string | null;
  time_precision: "date_only" | "datetime";
  reason?: string | null;
}) {
  return apiPost<ManualEventMutationResponse>("/events/manual", payload);
}

export async function updateManualEvent(
  entityUid: string,
  payload: {
    family_id: number;
    event_name: string;
    raw_type?: string | null;
    ordinal?: number | null;
    due_date: string;
    due_time?: string | null;
    time_precision: "date_only" | "datetime";
    reason?: string | null;
  }
) {
  return apiPatch<ManualEventMutationResponse>(`/events/manual/${encodeURIComponent(entityUid)}`, payload);
}

export async function deleteManualEvent(entityUid: string, reason?: string | null) {
  const query = buildQuery({ reason: reason || undefined });
  return apiDelete<ManualEventMutationResponse>(`/events/manual/${encodeURIComponent(entityUid)}${query}`);
}
