import { apiGet, apiPatch, apiPost, buildQuery } from "@/lib/api/client";
import type {
  CourseIdentity,
  CourseWorkItemFamily,
  CourseWorkItemFamilyStatus,
  CourseWorkItemRawType,
  CourseWorkItemRawTypeMoveResponse,
  RawTypeSuggestionDecisionResponse,
  RawTypeSuggestionItem,
} from "@/lib/types";

export function familiesListCacheKey(params?: {
  course_dept?: string | null;
  course_number?: number | null;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
}) {
  return `families:list${buildQuery(params || {})}`;
}

export function familiesStatusCacheKey() {
  return "families:status";
}

export function familiesCoursesCacheKey() {
  return "families:courses";
}

export function familiesRawTypesCacheKey(params?: {
  course_dept?: string | null;
  course_number?: number | null;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
  family_id?: number | null;
}) {
  return `families:raw-types${buildQuery(params || {})}`;
}

export function familiesSuggestionsCacheKey(params?: {
  status?: "pending" | "approved" | "rejected" | "dismissed" | "all";
  course_dept?: string | null;
  course_number?: number | null;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
  limit?: number;
  offset?: number;
}) {
  return `families:suggestions${buildQuery({ status: "pending", ...(params || {}) })}`;
}

export async function listFamilies(params?: {
  course_dept?: string | null;
  course_number?: number | null;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
}) {
  return apiGet<CourseWorkItemFamily[]>(`/families${buildQuery(params || {})}`);
}

export async function createFamily(payload: {
  course_dept: string;
  course_number: number;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
  canonical_label: string;
  raw_types: string[];
}) {
  return apiPost<CourseWorkItemFamily>("/families", payload);
}

export async function updateFamily(
  familyId: number,
  payload: {
    canonical_label: string;
    raw_types: string[];
  },
) {
  return apiPatch<CourseWorkItemFamily>(`/families/${familyId}`, payload);
}

export async function getFamiliesStatus() {
  return apiGet<CourseWorkItemFamilyStatus>("/families/status");
}

export async function listFamilyCourses() {
  return apiGet<{ courses: CourseIdentity[] }>("/families/courses");
}

export async function listFamilyRawTypes(params?: {
  course_dept?: string | null;
  course_number?: number | null;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
  family_id?: number | null;
}) {
  return apiGet<CourseWorkItemRawType[]>(`/families/raw-types${buildQuery(params || {})}`);
}

export async function relinkFamilyRawType(payload: {
  raw_type_id: number;
  family_id: number;
  note?: string | null;
}) {
  return apiPost<CourseWorkItemRawTypeMoveResponse>("/families/raw-types/relink", payload);
}

export async function listFamilyRawTypeSuggestions(params?: {
  status?: "pending" | "approved" | "rejected" | "dismissed" | "all";
  course_dept?: string | null;
  course_number?: number | null;
  course_suffix?: string | null;
  course_quarter?: string | null;
  course_year2?: number | null;
  limit?: number;
  offset?: number;
}) {
  return apiGet<RawTypeSuggestionItem[]>(`/families/raw-type-suggestions${buildQuery({ status: "pending", ...(params || {}) })}`);
}

export async function decideFamilyRawTypeSuggestion(
  suggestionId: number,
  payload: {
    decision: "approve" | "reject" | "dismiss";
    note?: string | null;
  },
) {
  return apiPost<RawTypeSuggestionDecisionResponse>(`/families/raw-type-suggestions/${suggestionId}/decisions`, payload);
}
