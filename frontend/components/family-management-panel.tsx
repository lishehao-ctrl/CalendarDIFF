"use client";

import Link from "next/link";
import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRightLeft, ChevronDown, ChevronUp, Search, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import {
  decideRawTypeSuggestion,
  getCourseWorkItemFamilyStatus,
  listCourseWorkItemFamilies,
  listCourseWorkItemRawTypes,
  listKnownCourseKeys,
  listRawTypeSuggestions,
  moveCourseRawTypeToFamily,
  updateCourseWorkItemFamily,
} from "@/lib/api/users";
import { withBasePath } from "@/lib/demo-mode";
import { useApiResource } from "@/lib/use-api-resource";
import { formatDateTime } from "@/lib/presenters";
import type {
  CourseIdentity,
  CourseWorkItemFamily,
  CourseWorkItemFamilyStatus,
  CourseWorkItemRawType,
  RawTypeSuggestionItem,
} from "@/lib/types";

type CourseIdentityForm = {
  course_dept: string;
  course_number: string;
  course_suffix: string;
  course_quarter: string;
  course_year2: string;
};

type FamilyWorkspaceResources = {
  families: ReturnType<typeof useApiResource<CourseWorkItemFamily[]>>;
  status: ReturnType<typeof useApiResource<CourseWorkItemFamilyStatus>>;
  courses: ReturnType<typeof useApiResource<{ courses: CourseIdentity[] }>>;
  rawTypes: ReturnType<typeof useApiResource<CourseWorkItemRawType[]>>;
  suggestions: ReturnType<typeof useApiResource<RawTypeSuggestionItem[]>>;
};

type FamilyDetailSection = "overview" | "duplicates" | "relink" | "advanced";

function emptyCourseIdentity(): CourseIdentityForm {
  return { course_dept: "", course_number: "", course_suffix: "", course_quarter: "", course_year2: "" };
}

function normalizeCourseIdentityForm(identity: CourseIdentityForm) {
  const dept = identity.course_dept.trim().toUpperCase();
  const courseNumber = Number(identity.course_number);
  if (!dept || !Number.isFinite(courseNumber)) {
    return null;
  }
  const quarter = identity.course_quarter.trim().toUpperCase();
  const year2 = identity.course_year2.trim();
  return {
    course_dept: dept,
    course_number: courseNumber,
    course_suffix: identity.course_suffix.trim().toUpperCase() || null,
    course_quarter: quarter || null,
    course_year2: year2 ? Number(year2) : null,
  };
}

function compareFamilyRows(left: CourseWorkItemFamily, right: CourseWorkItemFamily) {
  const courseCompare = left.course_display.localeCompare(right.course_display);
  if (courseCompare !== 0) return courseCompare;
  const labelCompare = left.canonical_label.localeCompare(right.canonical_label);
  if (labelCompare !== 0) return labelCompare;
  return left.id - right.id;
}

function familyMatchesCourse(family: CourseWorkItemFamily, selectedCourse: string | null) {
  return !selectedCourse || family.course_display === selectedCourse;
}

function rawTypeMatchesCourse(rawType: CourseWorkItemRawType, selectedCourse: string | null) {
  return !selectedCourse || rawType.course_display === selectedCourse;
}

function suggestionMatchesCourse(suggestion: RawTypeSuggestionItem, selectedCourse: string | null) {
  return !selectedCourse || suggestion.course_display === selectedCourse;
}

function suggestionMatchesQuery(suggestion: RawTypeSuggestionItem, query: string) {
  if (!query) return true;
  const haystack = [
    suggestion.course_display,
    suggestion.source_family_name,
    suggestion.suggested_family_name,
    suggestion.source_raw_type,
    suggestion.suggested_raw_type,
    suggestion.evidence,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(query);
}

function familyMatchesQuery(family: CourseWorkItemFamily, query: string) {
  if (!query) return true;
  const haystack = [family.course_display, family.canonical_label, ...family.raw_types].join(" ").toLowerCase();
  return haystack.includes(query);
}

function buildNeedsAttentionFamilies(families: CourseWorkItemFamily[], suggestions: RawTypeSuggestionItem[]) {
  const suggestionFamilyIds = new Map<number, number>();

  for (const suggestion of suggestions) {
    if (typeof suggestion.source_family_id === "number") {
      suggestionFamilyIds.set(suggestion.source_family_id, (suggestionFamilyIds.get(suggestion.source_family_id) || 0) + 1);
    }
    if (typeof suggestion.suggested_family_id === "number") {
      suggestionFamilyIds.set(suggestion.suggested_family_id, (suggestionFamilyIds.get(suggestion.suggested_family_id) || 0) + 1);
    }
  }

  return families
    .filter((family) => suggestionFamilyIds.has(family.id) || family.raw_types.length >= 3)
    .sort((left, right) => {
      const leftSuggestionCount = suggestionFamilyIds.get(left.id) || 0;
      const rightSuggestionCount = suggestionFamilyIds.get(right.id) || 0;
      if (rightSuggestionCount !== leftSuggestionCount) return rightSuggestionCount - leftSuggestionCount;
      if (right.raw_types.length !== left.raw_types.length) return right.raw_types.length - left.raw_types.length;
      return compareFamilyRows(left, right);
    });
}

function familyAttentionReason(family: CourseWorkItemFamily, suggestions: RawTypeSuggestionItem[]) {
  const relatedSuggestions = suggestions.filter((suggestion) => suggestion.source_family_id === family.id || suggestion.suggested_family_id === family.id);
  if (relatedSuggestions.length > 0) {
    return `${relatedSuggestions.length} pending duplicate clue${relatedSuggestions.length === 1 ? "" : "s"}`;
  }
  if (family.raw_types.length >= 3) {
    return `${family.raw_types.length} raw labels`;
  }
  return "Needs review";
}

function dedupeCourses(courses: CourseIdentity[]) {
  const deduped = new Map<string, CourseIdentity>();
  for (const course of courses) {
    if (!deduped.has(course.course_display)) {
      deduped.set(course.course_display, course);
    }
  }
  return Array.from(deduped.values()).sort((left, right) => left.course_display.localeCompare(right.course_display));
}

function splitCourseChips(courses: CourseIdentity[], selectedCourse: string | null, maxVisible = 3) {
  const primaryMap = new Map<string, CourseIdentity>();
  for (const course of courses.slice(0, maxVisible)) {
    primaryMap.set(course.course_display, course);
  }
  if (selectedCourse) {
    const selected = courses.find((course) => course.course_display === selectedCourse);
    if (selected) {
      primaryMap.set(selected.course_display, selected);
    }
  }
  const primary = Array.from(primaryMap.values());
  const overflow = courses.filter((course) => !primaryMap.has(course.course_display));
  return { primary, overflow };
}

function useFamilyWorkspaceResources(): FamilyWorkspaceResources {
  return {
    families: useApiResource<CourseWorkItemFamily[]>(() => listCourseWorkItemFamilies(), []),
    status: useApiResource<CourseWorkItemFamilyStatus>(() => getCourseWorkItemFamilyStatus(), []),
    courses: useApiResource<{ courses: CourseIdentity[] }>(() => listKnownCourseKeys(), []),
    rawTypes: useApiResource<CourseWorkItemRawType[]>(() => listCourseWorkItemRawTypes(), []),
    suggestions: useApiResource<RawTypeSuggestionItem[]>(() => listRawTypeSuggestions({ status: "pending", limit: 100 }), []),
  };
}

function renderWorkspaceState(resources: FamilyWorkspaceResources) {
  if (resources.families.loading || resources.status.loading || resources.courses.loading || resources.rawTypes.loading || resources.suggestions.loading) {
    return <LoadingState label="families" />;
  }
  if (resources.families.error) return <ErrorState message={`Families list failed to load. ${resources.families.error}`} />;
  if (resources.status.error) return <ErrorState message={`Families status failed to load. ${resources.status.error}`} />;
  if (resources.courses.error) return <ErrorState message={`Course filter data failed to load. ${resources.courses.error}`} />;
  if (resources.rawTypes.error) return <ErrorState message={`Raw label data failed to load. ${resources.rawTypes.error}`} />;
  if (resources.suggestions.error) return <ErrorState message={`Duplicate clues failed to load. ${resources.suggestions.error}`} />;
  return null;
}

function CompactFilters({
  query,
  onQueryChange,
  selectedCourse,
  onSelectCourse,
  courses,
}: {
  query: string;
  onQueryChange: (value: string) => void;
  selectedCourse: string | null;
  onSelectCourse: (value: string | null) => void;
  courses: CourseIdentity[];
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const { primary, overflow } = useMemo(() => splitCourseChips(courses, selectedCourse), [courses, selectedCourse]);

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
      <div className="relative min-w-0 flex-1 lg:max-w-md">
        <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-[#7d8794]" />
        <Input
          className="pl-11"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Filter by course, family, or raw label"
        />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant={selectedCourse === null ? "secondary" : "ghost"} onClick={() => onSelectCourse(null)}>
          All courses
        </Button>
        {primary.map((course) => (
          <Button
            key={course.course_display}
            size="sm"
            variant={selectedCourse === course.course_display ? "secondary" : "ghost"}
            onClick={() => {
              onSelectCourse(course.course_display);
              setMenuOpen(false);
            }}
          >
            {course.course_display}
          </Button>
        ))}
        {overflow.length > 0 ? (
          <Button size="sm" variant={menuOpen ? "secondary" : "ghost"} onClick={() => setMenuOpen((current) => !current)}>
            More
            {menuOpen ? <ChevronUp className="ml-2 h-4 w-4" /> : <ChevronDown className="ml-2 h-4 w-4" />}
          </Button>
        ) : null}
      </div>
    </div>
      {menuOpen ? (
        <Card className="animate-section-enter p-4">
          <div className="flex flex-wrap gap-2">
            {overflow.map((course) => (
              <Button
                key={course.course_display}
                size="sm"
                variant={selectedCourse === course.course_display ? "secondary" : "ghost"}
                onClick={() => {
                  onSelectCourse(course.course_display);
                  setMenuOpen(false);
                }}
              >
                {course.course_display}
              </Button>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  );
}

export function FamilyManagementPanel({ basePath = "" }: { basePath?: string }) {
  const resources = useFamilyWorkspaceResources();
  const workspaceState = renderWorkspaceState(resources);
  const [courseQuery, setCourseQuery] = useState("");
  const [selectedCourse, setSelectedCourse] = useState<string | null>(null);

  const deferredQuery = useDeferredValue(courseQuery.trim().toLowerCase());
  const courseOptions = useMemo(() => dedupeCourses(resources.courses.data?.courses || []), [resources.courses.data]);
  const visibleFamilies = useMemo(() => {
    return [...(resources.families.data || [])]
      .sort(compareFamilyRows)
      .filter((family) => familyMatchesCourse(family, selectedCourse))
      .filter((family) => familyMatchesQuery(family, deferredQuery));
  }, [deferredQuery, resources.families.data, selectedCourse]);
  const visibleSuggestions = useMemo(() => {
    return (resources.suggestions.data || [])
      .filter((suggestion) => suggestionMatchesCourse(suggestion, selectedCourse))
      .filter((suggestion) => suggestionMatchesQuery(suggestion, deferredQuery));
  }, [deferredQuery, resources.suggestions.data, selectedCourse]);
  const attentionFamilies = useMemo(() => buildNeedsAttentionFamilies(visibleFamilies, visibleSuggestions), [visibleFamilies, visibleSuggestions]);

  if (workspaceState) {
    return workspaceState;
  }

  return (
    <div className="space-y-5">
      <Card className="animate-surface-enter relative overflow-hidden p-6 md:p-7">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.13),transparent_36%),radial-gradient(circle_at_84%_20%,rgba(215,90,45,0.11),transparent_24%)]" />
        <div className="relative space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-3xl">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Families</p>
              <h2 className="mt-3 text-3xl font-semibold text-ink">Review naming drift.</h2>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge tone="pending">{attentionFamilies.length} to review</Badge>
              <Badge tone="info">{visibleSuggestions.length} merge clues</Badge>
            </div>
          </div>

          <CompactFilters
            query={courseQuery}
            onQueryChange={setCourseQuery}
            selectedCourse={selectedCourse}
            onSelectCourse={setSelectedCourse}
            courses={courseOptions}
          />
        </div>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="animate-surface-enter animate-surface-delay-1 p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Needs attention</p>
              <h3 className="mt-1 text-lg font-semibold text-ink">Families to review</h3>
            </div>
            <Badge tone="pending">{attentionFamilies.length}</Badge>
          </div>

          <div className="mt-4 space-y-3">
            {attentionFamilies.length === 0 ? (
              <EmptyState title="No family drift right now" description="Nothing in the current slice needs family cleanup." />
            ) : (
              attentionFamilies.slice(0, 8).map((family) => (
                <Link
                  key={family.id}
                  href={withBasePath(basePath, `/families/${family.id}`)}
                  className="animate-surface-enter interactive-lift block rounded-[1.1rem] border border-line/80 bg-white/72 p-4 transition-all duration-300 hover:-translate-y-0.5 hover:bg-white"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{family.course_display}</p>
                      <p className="mt-2 font-medium text-ink">{family.canonical_label}</p>
                      <p className="mt-2 text-sm text-[#596270]">{familyAttentionReason(family, visibleSuggestions)}</p>
                    </div>
                    <Badge tone={family.raw_types.length >= 3 ? "pending" : "info"}>{family.raw_types.length} raw</Badge>
                  </div>
                </Link>
              ))
            )}
          </div>
        </Card>

        <Card className="animate-surface-enter animate-surface-delay-2 p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Likely duplicates</p>
              <h3 className="mt-1 text-lg font-semibold text-ink">Merge clues</h3>
            </div>
            <Badge tone="info">{visibleSuggestions.length}</Badge>
          </div>

          <div className="mt-4 space-y-3">
            {visibleSuggestions.length === 0 ? (
              <div className="rounded-[1.1rem] border border-dashed border-line/80 bg-white/40 p-5 text-sm text-[#596270]">
                No duplicate clues in the current slice.
              </div>
            ) : (
              visibleSuggestions.slice(0, 8).map((suggestion) => (
                <div key={suggestion.id} className="rounded-[1.1rem] border border-line/80 bg-white/72 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2 text-sm font-medium text-ink">
                        <ArrowRightLeft className="h-4 w-4 text-cobalt" />
                        {suggestion.source_family_name || "Unknown"} → {suggestion.suggested_family_name || "Target"}
                      </div>
                      <p className="mt-2 text-xs uppercase tracking-[0.18em] text-[#6d7885]">{suggestion.course_display}</p>
                      <p className="mt-2 text-sm text-[#596270]">{suggestion.source_raw_type || "Unknown"} → {suggestion.suggested_raw_type || "Suggested"}</p>
                    </div>
                    <Badge tone="info">{Math.round(suggestion.confidence * 100)}%</Badge>
                  </div>
                  <div className="mt-4">
                    <Button asChild size="sm" variant="ghost">
                      <Link href={withBasePath(basePath, `/families/${suggestion.suggested_family_id || suggestion.source_family_id || ""}`)}>
                        Open family
                      </Link>
                    </Button>
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

export function FamilyDetailPanel({ familyId, basePath = "" }: { familyId: number; basePath?: string }) {
  const resources = useFamilyWorkspaceResources();
  const workspaceState = renderWorkspaceState(resources);
  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [busyFamily, setBusyFamily] = useState<number | null>(null);
  const [busySuggestionId, setBusySuggestionId] = useState<number | null>(null);
  const [busyMoveId, setBusyMoveId] = useState<number | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [activeSection, setActiveSection] = useState<FamilyDetailSection>("overview");
  const [draftCourseIdentity, setDraftCourseIdentity] = useState<CourseIdentityForm>(emptyCourseIdentity());
  const [draftLabel, setDraftLabel] = useState("");

  const family = useMemo(
    () => (resources.families.data || []).find((item) => item.id === familyId) || null,
    [familyId, resources.families.data],
  );
  const selectedSuggestions = useMemo(() => {
    if (!family) return [];
    return (resources.suggestions.data || []).filter((suggestion) => suggestion.source_family_id === family.id || suggestion.suggested_family_id === family.id);
  }, [family, resources.suggestions.data]);
  const selectedRawTypes = useMemo(() => {
    if (!family) return [];
    return (resources.rawTypes.data || [])
      .filter((rawType) => rawType.family_id === family.id)
      .sort((left, right) => left.raw_type.localeCompare(right.raw_type));
  }, [family, resources.rawTypes.data]);
  const moveCandidates = useMemo(() => {
    if (!family) return [];
    return (resources.rawTypes.data || [])
      .filter((rawType) => rawType.course_display === family.course_display && rawType.family_id !== family.id)
      .sort((left, right) => left.raw_type.localeCompare(right.raw_type));
  }, [family, resources.rawTypes.data]);

  useEffect(() => {
    if (!family) return;
    setDraftLabel(family.canonical_label);
    setDraftCourseIdentity({
      course_dept: family.course_dept,
      course_number: String(family.course_number),
      course_suffix: family.course_suffix || "",
      course_quarter: family.course_quarter || "",
      course_year2: family.course_year2 != null ? String(family.course_year2).padStart(2, "0") : "",
    });
  }, [family]);

  useEffect(() => {
    if (activeSection === "duplicates" && selectedSuggestions.length === 0) {
      setActiveSection("overview");
    }
    if (activeSection === "relink" && moveCandidates.length === 0) {
      setActiveSection("overview");
    }
  }, [activeSection, moveCandidates.length, selectedSuggestions.length]);

  async function refreshAll() {
    await Promise.all([
      resources.families.refresh(),
      resources.status.refresh(),
      resources.courses.refresh(),
      resources.rawTypes.refresh(),
      resources.suggestions.refresh(),
    ]);
  }

  async function saveFamily() {
    if (!family) return;
    const canonicalLabel = draftLabel.trim();
    const identity = normalizeCourseIdentityForm(draftCourseIdentity);
    if (!canonicalLabel || !identity) return;

    setBusyFamily(family.id);
    setBanner(null);
    try {
      await updateCourseWorkItemFamily(family.id, {
        ...identity,
        canonical_label: canonicalLabel,
        raw_types: selectedRawTypes.map((item) => item.raw_type),
      });
      setBanner({ tone: "info", text: `Updated ${canonicalLabel}.` });
      await refreshAll();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to update family" });
    } finally {
      setBusyFamily(null);
    }
  }

  async function decideSuggestion(suggestionId: number, decision: "approve" | "reject" | "dismiss") {
    setBusySuggestionId(suggestionId);
    setBanner(null);
    try {
      await decideRawTypeSuggestion(suggestionId, { decision, note: `ui_${decision}` });
      setBanner({
        tone: "info",
        text:
          decision === "approve"
            ? "Approved duplicate clue."
            : decision === "reject"
              ? "Rejected duplicate clue."
              : "Dismissed duplicate clue.",
      });
      await refreshAll();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to update duplicate clue" });
    } finally {
      setBusySuggestionId(null);
    }
  }

  async function moveRawType(rawTypeId: number) {
    if (!family) return;
    setBusyMoveId(rawTypeId);
    setBanner(null);
    try {
      await moveCourseRawTypeToFamily({ raw_type_id: rawTypeId, family_id: family.id, note: "ui_manual_relink" });
      setBanner({ tone: "info", text: "Moved raw label into this family." });
      await refreshAll();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to move raw label" });
    } finally {
      setBusyMoveId(null);
    }
  }

  if (workspaceState) {
    return workspaceState;
  }

  if (!family) {
    return <EmptyState title="Family not found" description="This family no longer exists in the current workspace state." />;
  }

  const sectionOptions: Array<{ id: FamilyDetailSection; label: string; hidden?: boolean }> = [
    { id: "overview", label: "Overview" },
    { id: "duplicates", label: "Duplicates", hidden: selectedSuggestions.length === 0 },
    { id: "relink", label: "Relink", hidden: moveCandidates.length === 0 },
    { id: "advanced", label: "Advanced" },
  ];

  return (
    <div className="space-y-5">
      <Card className="animate-surface-enter p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <Button asChild size="sm" variant="ghost">
              <Link href={withBasePath(basePath, "/families")}>
                <ArrowLeft className="mr-2 h-4 w-4" />
                Back to Families
              </Link>
            </Button>
            <p className="mt-4 text-xs uppercase tracking-[0.18em] text-[#6d7885]">Family detail</p>
            <h2 className="mt-2 text-3xl font-semibold text-ink">{family.canonical_label}</h2>
            <p className="mt-2 text-sm text-[#596270]">{family.course_display}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge tone={selectedSuggestions.length > 0 || selectedRawTypes.length >= 3 ? "pending" : "approved"}>
              {selectedSuggestions.length > 0 || selectedRawTypes.length >= 3 ? "Needs attention" : "Stable"}
            </Badge>
            <Badge tone="info">{selectedRawTypes.length} raw labels</Badge>
          </div>
        </div>
      </Card>

      {banner ? (
        <Card className={banner.tone === "error" ? "animate-surface-enter border-[#efc4b5] bg-[#fff3ef] p-4" : "animate-surface-enter border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] p-4"}>
          <p className="text-sm text-[#314051]">{banner.text}</p>
        </Card>
      ) : null}

      <div className="grid gap-3 md:grid-cols-4">
        <Card className="animate-surface-enter animate-surface-delay-1 p-4">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Status</p>
          <p className="mt-2 text-sm font-medium text-ink">{familyAttentionReason(family, selectedSuggestions)}</p>
        </Card>
        <Card className="animate-surface-enter animate-surface-delay-1 p-4">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Duplicate clues</p>
          <p className="mt-2 text-sm font-medium text-ink">{selectedSuggestions.length}</p>
        </Card>
        <Card className="animate-surface-enter animate-surface-delay-2 p-4">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Relink candidates</p>
          <p className="mt-2 text-sm font-medium text-ink">{moveCandidates.length}</p>
        </Card>
        <Card className="animate-surface-enter animate-surface-delay-2 p-4">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Last rebuild</p>
          <p className="mt-2 text-sm font-medium text-ink">{formatDateTime(resources.status.data?.last_rebuilt_at, "Never")}</p>
        </Card>
      </div>

      <div className="inline-flex flex-wrap gap-2 rounded-full border border-line/80 bg-white/72 p-2">
        {sectionOptions
          .filter((section) => !section.hidden)
          .map((section) => (
            <Button
              key={section.id}
              size="sm"
              variant={activeSection === section.id ? "secondary" : "ghost"}
              onClick={() => setActiveSection(section.id)}
            >
              {section.label}
            </Button>
          ))}
      </div>

      {activeSection === "overview" ? (
        <div className="space-y-4">
          <Card className="animate-surface-enter animate-surface-delay-1 p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Canonical rename</p>
              </div>
              <Button onClick={() => void saveFamily()} disabled={busyFamily === family.id || !draftLabel.trim()}>
                {busyFamily === family.id ? "Saving..." : "Save family"}
              </Button>
            </div>
            <div className="mt-4">
              <Input value={draftLabel} onChange={(event) => setDraftLabel(event.target.value)} placeholder="Canonical label" />
            </div>
          </Card>

          <Card className="animate-surface-enter animate-surface-delay-2 p-5">
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Observed labels</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {selectedRawTypes.map((rawType) => (
                <Badge key={`${family.id}-${rawType.id}`} tone="info">
                  {rawType.raw_type}
                </Badge>
              ))}
            </div>
          </Card>
        </div>
      ) : null}

      {activeSection === "duplicates" ? (
        <Card className="animate-surface-enter animate-surface-delay-2 p-5">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-cobalt" />
            <p className="text-sm font-medium text-ink">Duplicate clues</p>
          </div>
          <div className="mt-4 space-y-3">
            {selectedSuggestions.length === 0 ? (
              <p className="text-sm text-[#596270]">No duplicate clues are attached to this family.</p>
            ) : (
              selectedSuggestions.map((suggestion) => (
                <div key={suggestion.id} className="rounded-[1rem] border border-line/80 bg-white/80 p-4">
                  <p className="text-sm font-medium text-ink">
                    {suggestion.source_raw_type || "Unknown"} → {suggestion.suggested_family_name || "Target"}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button size="sm" disabled={busySuggestionId === suggestion.id} onClick={() => void decideSuggestion(suggestion.id, "approve")}>
                      {busySuggestionId === suggestion.id ? "Applying..." : "Approve"}
                    </Button>
                    <Button size="sm" variant="ghost" disabled={busySuggestionId === suggestion.id} onClick={() => void decideSuggestion(suggestion.id, "reject")}>
                      Reject
                    </Button>
                    <Button size="sm" variant="ghost" disabled={busySuggestionId === suggestion.id} onClick={() => void decideSuggestion(suggestion.id, "dismiss")}>
                      Dismiss
                    </Button>
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>
      ) : null}

      {activeSection === "relink" ? (
        <Card className="animate-surface-enter animate-surface-delay-2 p-5">
          <p className="text-sm font-medium text-ink">Raw-label relink</p>
          <div className="mt-4 space-y-3">
            {moveCandidates.length === 0 ? (
              <p className="text-sm text-[#596270]">No raw-label relink candidates for this family.</p>
            ) : (
              moveCandidates.map((rawType) => (
                <div key={rawType.id} className="flex flex-wrap items-center justify-between gap-3 rounded-[1rem] border border-line/80 bg-white/80 p-4">
                  <div>
                    <p className="text-sm font-medium text-ink">{rawType.raw_type}</p>
                    <p className="mt-1 text-xs text-[#596270]">Currently attached to family #{rawType.family_id}</p>
                  </div>
                  <Button size="sm" disabled={busyMoveId === rawType.id} onClick={() => void moveRawType(rawType.id)}>
                    {busyMoveId === rawType.id ? "Moving..." : "Move here"}
                  </Button>
                </div>
              ))
            )}
          </div>
        </Card>
      ) : null}

      {activeSection === "advanced" ? (
        <Card className="animate-surface-enter animate-surface-delay-2 p-5">
          <button type="button" className="flex w-full items-center justify-between gap-4 text-left" onClick={() => setAdvancedOpen((current) => !current)}>
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Advanced</p>
              <p className="mt-1 text-sm font-medium text-ink">Course identity fields</p>
            </div>
            {advancedOpen ? <ChevronUp className="h-4 w-4 text-[#6d7885]" /> : <ChevronDown className="h-4 w-4 text-[#6d7885]" />}
          </button>

          {advancedOpen ? (
            <div className="mt-4 space-y-4">
              <div className="grid gap-3 md:grid-cols-5">
                <Input
                  value={draftCourseIdentity.course_dept}
                  onChange={(event) => setDraftCourseIdentity((prev) => ({ ...prev, course_dept: event.target.value }))}
                  placeholder="Dept"
                />
                <Input
                  value={draftCourseIdentity.course_number}
                  onChange={(event) => setDraftCourseIdentity((prev) => ({ ...prev, course_number: event.target.value }))}
                  placeholder="Number"
                />
                <Input
                  value={draftCourseIdentity.course_suffix}
                  onChange={(event) => setDraftCourseIdentity((prev) => ({ ...prev, course_suffix: event.target.value }))}
                  placeholder="Suffix"
                />
                <Input
                  value={draftCourseIdentity.course_quarter}
                  onChange={(event) => setDraftCourseIdentity((prev) => ({ ...prev, course_quarter: event.target.value }))}
                  placeholder="Quarter"
                />
                <Input
                  value={draftCourseIdentity.course_year2}
                  onChange={(event) => setDraftCourseIdentity((prev) => ({ ...prev, course_year2: event.target.value }))}
                  placeholder="Year2"
                />
              </div>
              <div>
                <Button onClick={() => void saveFamily()} disabled={busyFamily === family.id || !draftLabel.trim()}>
                  {busyFamily === family.id ? "Saving..." : "Save family"}
                </Button>
              </div>
            </div>
          ) : null}
        </Card>
      ) : null}
    </div>
  );
}
