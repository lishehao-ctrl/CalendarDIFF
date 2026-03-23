"use client";

import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { Plus, Search, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetDismissButton, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import {
  createFamily,
  decideFamilyRawTypeSuggestion,
  getFamiliesStatus,
  listFamilies,
  listFamilyCourses,
  listFamilyRawTypeSuggestions,
  listFamilyRawTypes,
  relinkFamilyRawType,
  updateFamily,
} from "@/lib/api/families";
import { listManualEvents } from "@/lib/api/manual";
import { translate } from "@/lib/i18n/runtime";
import { useApiResource } from "@/lib/use-api-resource";
import { formatDateTime, formatSemanticDue } from "@/lib/presenters";
import type {
  CourseIdentity,
  CourseWorkItemFamily,
  CourseWorkItemFamilyStatus,
  CourseWorkItemRawType,
  ManualEvent,
  RawTypeSuggestionItem,
} from "@/lib/types";

type WorkspaceArea = "families" | "raw-types" | "suggestions";

type CourseIdentityForm = {
  course_dept: string;
  course_number: string;
  course_suffix: string;
  course_quarter: string;
  course_year2: string;
};

const PAGE_SIZE = {
  families: 8,
  rawTypes: 10,
  suggestions: 8,
  events: 6,
} as const;

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

function parseRawTypeKeywords(input: string) {
  const seen = new Set<string>();
  return input
    .split(/[\n,;，]+/)
    .map((value) => value.trim())
    .filter(Boolean)
    .filter((value) => {
      const normalized = value.toLowerCase();
      if (seen.has(normalized)) {
        return false;
      }
      seen.add(normalized);
      return true;
    });
}

function dedupeCourses(courses: CourseIdentity[], families: CourseWorkItemFamily[]) {
  const deduped = new Map<string, CourseIdentity>();
  for (const course of courses) {
    if (!deduped.has(course.course_display)) {
      deduped.set(course.course_display, course);
    }
  }
  for (const family of families) {
    if (!deduped.has(family.course_display)) {
      deduped.set(family.course_display, {
        course_display: family.course_display,
        course_dept: family.course_dept,
        course_number: family.course_number,
        course_suffix: family.course_suffix,
        course_quarter: family.course_quarter,
        course_year2: family.course_year2,
      });
    }
  }
  return Array.from(deduped.values()).sort((left, right) => left.course_display.localeCompare(right.course_display));
}

function familyMatchesQuery(family: CourseWorkItemFamily, query: string) {
  if (!query) return true;
  const haystack = [family.course_display, family.canonical_label, ...family.raw_types].join(" ").toLowerCase();
  return haystack.includes(query);
}

function rawTypeMatchesQuery(rawType: CourseWorkItemRawType, familyLabel: string, query: string) {
  if (!query) return true;
  const haystack = [rawType.course_display, rawType.raw_type, familyLabel].join(" ").toLowerCase();
  return haystack.includes(query);
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

function compareFamilies(left: CourseWorkItemFamily, right: CourseWorkItemFamily) {
  const courseCompare = left.course_display.localeCompare(right.course_display);
  if (courseCompare !== 0) return courseCompare;
  const labelCompare = left.canonical_label.localeCompare(right.canonical_label);
  if (labelCompare !== 0) return labelCompare;
  return left.id - right.id;
}

function paginateRows<T>(rows: T[], page: number, pageSize: number) {
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const start = (safePage - 1) * pageSize;
  return {
    page: safePage,
    totalPages,
    rows: rows.slice(start, start + pageSize),
  };
}

function familyEventTitle(event: ManualEvent) {
  return event.event?.event_display.display_label || event.event_name || event.raw_type || translate("common.labels.unknown");
}

function compareManualEvents(left: ManualEvent, right: ManualEvent) {
  const leftDue = `${left.due_date || ""} ${left.due_time || ""}`.trim();
  const rightDue = `${right.due_date || ""} ${right.due_time || ""}`.trim();
  const dueCompare = leftDue.localeCompare(rightDue);
  if (dueCompare !== 0) return dueCompare;
  const titleCompare = familyEventTitle(left).localeCompare(familyEventTitle(right));
  if (titleCompare !== 0) return titleCompare;
  return left.entity_uid.localeCompare(right.entity_uid);
}

function PaginationControls({
  page,
  totalPages,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}) {
  if (totalPages <= 1) {
    return null;
  }
  return (
    <div className="mt-4 flex items-center justify-between gap-3 border-t border-line/80 pt-4 text-sm text-[#596270]">
      <span>Page {page} of {totalPages}</span>
      <div className="flex gap-2">
        <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
          {translate("common.actions.previous")}
        </Button>
        <Button size="sm" variant="ghost" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>
          {translate("common.actions.next")}
        </Button>
      </div>
    </div>
  );
}

export function FamilyManagementPanel({ basePath = "" }: { basePath?: string }) {
  void basePath;
  const families = useApiResource<CourseWorkItemFamily[]>(() => listFamilies(), []);
  const status = useApiResource<CourseWorkItemFamilyStatus>(() => getFamiliesStatus(), []);
  const courses = useApiResource<{ courses: CourseIdentity[] }>(() => listFamilyCourses(), []);
  const rawTypes = useApiResource<CourseWorkItemRawType[]>(() => listFamilyRawTypes(), []);
  const suggestions = useApiResource<RawTypeSuggestionItem[]>(() => listFamilyRawTypeSuggestions({ status: "pending", limit: 100 }), []);
  const manualEvents = useApiResource<ManualEvent[]>(() => listManualEvents(), []);

  const [workspaceArea, setWorkspaceArea] = useState<WorkspaceArea>("families");
  const [query, setQuery] = useState("");
  const [selectedCourse, setSelectedCourse] = useState<string>("all");
  const [selectedFamilyId, setSelectedFamilyId] = useState<number | null>(null);
  const [familyChooserOpen, setFamilyChooserOpen] = useState(false);
  const [familyPage, setFamilyPage] = useState(1);
  const [rawTypePage, setRawTypePage] = useState(1);
  const [suggestionPage, setSuggestionPage] = useState(1);
  const [eventPage, setEventPage] = useState(1);
  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [busyFamilyId, setBusyFamilyId] = useState<number | null>(null);
  const [busyCreate, setBusyCreate] = useState(false);
  const [busyRawTypeId, setBusyRawTypeId] = useState<number | null>(null);
  const [busySuggestionId, setBusySuggestionId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [draftLabel, setDraftLabel] = useState("");
  const [newCourseIdentity, setNewCourseIdentity] = useState<CourseIdentityForm>(emptyCourseIdentity());
  const [newCanonicalLabel, setNewCanonicalLabel] = useState("");
  const [newRawTypesInput, setNewRawTypesInput] = useState("");
  const [rawTypeTargets, setRawTypeTargets] = useState<Record<number, string>>({});
  const [relinkPreview, setRelinkPreview] = useState<{ rawTypeId: number; targetFamilyId: number } | null>(null);

  const deferredQuery = useDeferredValue(query.trim().toLowerCase());
  const familyRows = useMemo(() => [...(families.data || [])].sort(compareFamilies), [families.data]);
  const courseOptions = useMemo(() => dedupeCourses(courses.data?.courses || [], familyRows), [courses.data, familyRows]);
  const familyLabelById = useMemo(
    () => Object.fromEntries(familyRows.map((family) => [family.id, family.canonical_label])),
    [familyRows],
  );
  const selectedCourseRows = useMemo(
    () => familyRows.filter((family) => selectedCourse === "all" || family.course_display === selectedCourse),
    [familyRows, selectedCourse],
  );
  const visibleFamilies = useMemo(
    () => selectedCourseRows.filter((family) => familyMatchesQuery(family, deferredQuery)),
    [deferredQuery, selectedCourseRows],
  );
  const visibleRawTypes = useMemo(
    () =>
      (rawTypes.data || []).filter((rawType) => {
        if (selectedCourse !== "all" && rawType.course_display !== selectedCourse) {
          return false;
        }
        return rawTypeMatchesQuery(rawType, familyLabelById[rawType.family_id] || "", deferredQuery);
      }),
    [deferredQuery, familyLabelById, rawTypes.data, selectedCourse],
  );
  const visibleSuggestions = useMemo(
    () =>
      (suggestions.data || []).filter((suggestion) => {
        if (selectedCourse !== "all" && suggestion.course_display !== selectedCourse) {
          return false;
        }
        return suggestionMatchesQuery(suggestion, deferredQuery);
      }),
    [deferredQuery, selectedCourse, suggestions.data],
  );

  useEffect(() => {
    setFamilyPage(1);
    setRawTypePage(1);
    setSuggestionPage(1);
    setEventPage(1);
  }, [deferredQuery, selectedCourse, workspaceArea]);

  useEffect(() => {
    if (visibleFamilies.length === 0) {
      setSelectedFamilyId(null);
      return;
    }
    if (!selectedFamilyId || !visibleFamilies.some((family) => family.id === selectedFamilyId)) {
      setSelectedFamilyId(visibleFamilies[0].id);
    }
  }, [selectedFamilyId, visibleFamilies]);

  const selectedFamily = useMemo(
    () => visibleFamilies.find((family) => family.id === selectedFamilyId) || visibleFamilies[0] || null,
    [selectedFamilyId, visibleFamilies],
  );
  const selectedFamilyRawTypes = useMemo(
    () =>
      selectedFamily
        ? (rawTypes.data || [])
            .filter((rawType) => rawType.family_id === selectedFamily.id)
            .sort((left, right) => left.raw_type.localeCompare(right.raw_type))
        : [],
    [rawTypes.data, selectedFamily],
  );
  const selectedFamilyEvents = useMemo(
    () =>
      selectedFamily
        ? [...((manualEvents.data || []).filter((event) => event.family_id === selectedFamily.id))].sort(compareManualEvents)
        : [],
    [manualEvents.data, selectedFamily],
  );
  const eventCountByFamilyId = useMemo(() => {
    const counts = new Map<number, number>();
    for (const event of manualEvents.data || []) {
      if (event.family_id == null) continue;
      counts.set(event.family_id, (counts.get(event.family_id) || 0) + 1);
    }
    return counts;
  }, [manualEvents.data]);
  const suggestionCountByFamilyId = useMemo(() => {
    const counts = new Map<number, number>();
    for (const suggestion of suggestions.data || []) {
      if (suggestion.source_family_id != null) {
        counts.set(suggestion.source_family_id, (counts.get(suggestion.source_family_id) || 0) + 1);
      }
      if (suggestion.suggested_family_id != null) {
        counts.set(suggestion.suggested_family_id, (counts.get(suggestion.suggested_family_id) || 0) + 1);
      }
    }
    return counts;
  }, [suggestions.data]);
  const eventRowsByObservedLabel = useMemo(() => {
    const rows = new Map<string, ManualEvent[]>();
    for (const event of manualEvents.data || []) {
      if (!event.raw_type) continue;
      const key = `${event.course_display}::${event.raw_type}`;
      if (!rows.has(key)) rows.set(key, []);
      rows.get(key)!.push(event);
    }
    return rows;
  }, [manualEvents.data]);
  const suggestionCountByObservedLabel = useMemo(() => {
    const counts = new Map<string, number>();
    for (const suggestion of suggestions.data || []) {
      const pairs = [
        suggestion.source_raw_type ? `${suggestion.course_display}::${suggestion.source_raw_type}` : null,
        suggestion.suggested_raw_type ? `${suggestion.course_display}::${suggestion.suggested_raw_type}` : null,
      ];
      for (const key of pairs) {
        if (!key) continue;
        counts.set(key, (counts.get(key) || 0) + 1);
      }
    }
    return counts;
  }, [suggestions.data]);

  useEffect(() => {
    if (!selectedFamily) {
      setDraftLabel("");
      return;
    }
    setDraftLabel(selectedFamily.canonical_label);
  }, [selectedFamily]);

  useEffect(() => {
    setEventPage(1);
  }, [selectedFamilyId]);

  useEffect(() => {
    if (selectedCourse === "all") {
      return;
    }
    const scopedCourse = courseOptions.find((course) => course.course_display === selectedCourse);
    if (!scopedCourse) {
      return;
    }
    setNewCourseIdentity((current) => {
      if (current.course_dept || current.course_number || current.course_quarter || current.course_year2) {
        return current;
      }
      return {
        course_dept: scopedCourse.course_dept,
        course_number: String(scopedCourse.course_number),
        course_suffix: scopedCourse.course_suffix || "",
        course_quarter: scopedCourse.course_quarter || "",
        course_year2: scopedCourse.course_year2 != null ? String(scopedCourse.course_year2).padStart(2, "0") : "",
      };
    });
  }, [courseOptions, selectedCourse]);

  const pagedFamilies = paginateRows(visibleFamilies, familyPage, PAGE_SIZE.families);
  const pagedRawTypes = paginateRows(visibleRawTypes, rawTypePage, PAGE_SIZE.rawTypes);
  const pagedSuggestions = paginateRows(visibleSuggestions, suggestionPage, PAGE_SIZE.suggestions);
  const pagedEvents = paginateRows(selectedFamilyEvents, eventPage, PAGE_SIZE.events);
  const newRawTypes = useMemo(() => parseRawTypeKeywords(newRawTypesInput), [newRawTypesInput]);
  const relinkPreviewRawType = useMemo(
    () => (relinkPreview ? (rawTypes.data || []).find((row) => row.id === relinkPreview.rawTypeId) || null : null),
    [rawTypes.data, relinkPreview],
  );
  const relinkPreviewCurrentFamily = useMemo(
    () => (relinkPreviewRawType ? familyRows.find((family) => family.id === relinkPreviewRawType.family_id) || null : null),
    [familyRows, relinkPreviewRawType],
  );
  const relinkPreviewTargetFamily = useMemo(
    () => (relinkPreview ? familyRows.find((family) => family.id === relinkPreview.targetFamilyId) || null : null),
    [familyRows, relinkPreview],
  );
  const relinkPreviewEvents = useMemo(() => {
    if (!relinkPreviewRawType) return [];
    const key = `${relinkPreviewRawType.course_display}::${relinkPreviewRawType.raw_type}`;
    return [...(eventRowsByObservedLabel.get(key) || [])].sort(compareManualEvents).slice(0, 4);
  }, [eventRowsByObservedLabel, relinkPreviewRawType]);
  const relinkPreviewSuggestionCount = useMemo(() => {
    if (!relinkPreviewRawType) return 0;
    const key = `${relinkPreviewRawType.course_display}::${relinkPreviewRawType.raw_type}`;
    return suggestionCountByObservedLabel.get(key) || 0;
  }, [relinkPreviewRawType, suggestionCountByObservedLabel]);

  async function refreshAll() {
    await Promise.all([families.refresh(), status.refresh(), courses.refresh(), rawTypes.refresh(), suggestions.refresh(), manualEvents.refresh()]);
  }

  async function saveSelectedFamily() {
    if (!selectedFamily) return;
    const canonicalLabel = draftLabel.trim();
    if (!canonicalLabel) {
      setBanner({ tone: "error", text: translate("families.banners.familyLabelRequired") });
      return;
    }

    setBusyFamilyId(selectedFamily.id);
    setBanner(null);
    try {
      await updateFamily(selectedFamily.id, {
        canonical_label: canonicalLabel,
        raw_types: selectedFamilyRawTypes.map((rawType) => rawType.raw_type),
      });
      setBanner({ tone: "info", text: translate("families.banners.updated", { label: canonicalLabel }) });
      await refreshAll();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("families.banners.updateFailed") });
    } finally {
      setBusyFamilyId(null);
    }
  }

  async function createNewFamily() {
    const identity = normalizeCourseIdentityForm(newCourseIdentity);
    const canonicalLabel = newCanonicalLabel.trim();
    if (!identity || !canonicalLabel) {
      setBanner({ tone: "error", text: translate("families.create.validation") });
      return;
    }

    setBusyCreate(true);
    setBanner(null);
    try {
      await createFamily({
        ...identity,
        canonical_label: canonicalLabel,
        raw_types: newRawTypes,
      });
      setNewCanonicalLabel("");
      setNewRawTypesInput("");
      setCreateOpen(false);
      setBanner({ tone: "info", text: translate("families.create.created", { label: canonicalLabel }) });
      await refreshAll();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("families.create.failed") });
    } finally {
      setBusyCreate(false);
    }
  }

  function previewMoveRawType(rawType: CourseWorkItemRawType) {
    const familyId = Number(rawTypeTargets[rawType.id] || rawType.family_id);
    if (!Number.isFinite(familyId) || familyId === rawType.family_id) {
      return;
    }
    setRelinkPreview({ rawTypeId: rawType.id, targetFamilyId: familyId });
  }

  async function confirmMoveRawType() {
    if (!relinkPreviewRawType || !relinkPreviewTargetFamily) {
      return;
    }
    setBusyRawTypeId(relinkPreviewRawType.id);
    setBanner(null);
    try {
      await relinkFamilyRawType({ raw_type_id: relinkPreviewRawType.id, family_id: relinkPreviewTargetFamily.id, note: "ui_family_governance" });
      setBanner({ tone: "info", text: translate("families.observed.moved", { label: relinkPreviewRawType.raw_type }) });
      setRelinkPreview(null);
      await refreshAll();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("families.observed.moveFailed") });
    } finally {
      setBusyRawTypeId(null);
    }
  }

  async function decideSuggestion(suggestionId: number, decision: "approve" | "reject" | "dismiss") {
    setBusySuggestionId(suggestionId);
    setBanner(null);
    try {
      await decideFamilyRawTypeSuggestion(suggestionId, { decision, note: `ui_${decision}` });
      setBanner({
        tone: "info",
        text:
          decision === "approve"
            ? translate("families.suggestions.approved")
            : decision === "reject"
              ? translate("families.suggestions.rejected")
              : translate("families.suggestions.dismissed"),
      });
      await refreshAll();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("families.suggestions.failed") });
    } finally {
      setBusySuggestionId(null);
    }
  }

  if (families.loading || status.loading || courses.loading || rawTypes.loading || suggestions.loading) {
    return <LoadingState label={translate("common.loadingLabels.families")} />;
  }
  if (families.error) return <ErrorState message={`Families failed to load. ${families.error}`} />;
  if (status.error) return <ErrorState message={`Families status failed to load. ${status.error}`} />;
  if (courses.error) return <ErrorState message={`Course scope failed to load. ${courses.error}`} />;
  if (rawTypes.error) return <ErrorState message={`Observed labels failed to load. ${rawTypes.error}`} />;
  if (suggestions.error) return <ErrorState message={`Suggestions failed to load. ${suggestions.error}`} />;

  return (
    <div className="space-y-5">
      <Card className="animate-surface-enter relative overflow-hidden p-6 md:p-7">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.13),transparent_36%),radial-gradient(circle_at_84%_20%,rgba(215,90,45,0.11),transparent_24%)]" />
        <div className="relative space-y-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-3xl">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("families.heroEyebrow")}</p>
              <h2 className="mt-3 text-3xl font-semibold text-ink">{translate("families.heroTitle")}</h2>
              <p className="mt-3 text-sm text-[#596270]">{translate("families.heroSummary")}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge tone="info">{translate("families.counts.families", { count: familyRows.length })}</Badge>
              <Badge tone="info">{translate("families.counts.observedLabels", { count: (rawTypes.data || []).length })}</Badge>
              <Badge tone={visibleSuggestions.length > 0 ? "pending" : "approved"}>{translate("families.counts.suggestions", { count: visibleSuggestions.length })}</Badge>
            </div>
          </div>

          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_260px]">
            <div className="relative">
              <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-[#7d8794]" />
              <Input
                className="pl-11"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={translate("families.searchPlaceholder")}
              />
            </div>
            <select
              aria-label={translate("changes.course")}
              className="h-11 rounded-2xl border border-line bg-white/80 px-4 text-sm text-ink outline-none transition focus:border-cobalt focus:bg-white"
              value={selectedCourse}
              onChange={(event) => setSelectedCourse(event.target.value)}
            >
              <option value="all">{translate("families.allCourses")}</option>
              {courseOptions.map((course) => (
                <option key={course.course_display} value={course.course_display}>
                  {course.course_display}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant={workspaceArea === "families" ? "secondary" : "ghost"} onClick={() => setWorkspaceArea("families")}>
              {translate("families.areas.families")}
            </Button>
            <Button size="sm" variant={workspaceArea === "raw-types" ? "secondary" : "ghost"} onClick={() => setWorkspaceArea("raw-types")}>
              {translate("families.areas.observedLabels")}
            </Button>
            <Button size="sm" variant={workspaceArea === "suggestions" ? "secondary" : "ghost"} onClick={() => setWorkspaceArea("suggestions")}>
              {translate("families.areas.suggestions")}
            </Button>
            <Badge tone="info">{translate("families.lastRebuild", { time: formatDateTime(status.data?.last_rebuilt_at, translate("sources.detail.never")) })}</Badge>
          </div>
        </div>
      </Card>

      {banner ? (
        <Card className={banner.tone === "error" ? "border-[#efc4b5] bg-[#fff3ef] p-4" : "border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] p-4"}>
          <p className="text-sm text-[#314051]">{banner.text}</p>
        </Card>
      ) : null}

      {workspaceArea === "families" ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(340px,0.9fr)_minmax(0,1.1fr)]">
          <Card className="order-2 animate-surface-enter p-5 xl:order-1">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("families.areas.families")}</p>
                <h3 className="mt-1 text-lg font-semibold text-ink">{translate("families.list.title")}</h3>
              </div>
              <Button size="sm" variant={createOpen ? "secondary" : "ghost"} onClick={() => setCreateOpen((current) => !current)}>
                <Plus className="mr-2 h-4 w-4" />
                {translate("families.list.addFamily")}
              </Button>
            </div>

            {createOpen ? (
              <div className="mt-4 rounded-[1.15rem] border border-line/80 bg-white/70 p-4">
                <p className="text-sm font-medium text-ink">{translate("families.create.title")}</p>
                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  <Input value={newCanonicalLabel} onChange={(event) => setNewCanonicalLabel(event.target.value)} placeholder={translate("families.create.canonicalLabel")} />
                  <Input value={newCourseIdentity.course_dept} onChange={(event) => setNewCourseIdentity((current) => ({ ...current, course_dept: event.target.value }))} placeholder={translate("families.create.dept")} />
                  <Input value={newCourseIdentity.course_number} onChange={(event) => setNewCourseIdentity((current) => ({ ...current, course_number: event.target.value }))} placeholder={translate("families.create.number")} />
                  <Input value={newCourseIdentity.course_suffix} onChange={(event) => setNewCourseIdentity((current) => ({ ...current, course_suffix: event.target.value }))} placeholder={translate("families.create.suffix")} />
                  <Input value={newCourseIdentity.course_quarter} onChange={(event) => setNewCourseIdentity((current) => ({ ...current, course_quarter: event.target.value }))} placeholder={translate("families.create.quarter")} />
                  <Input value={newCourseIdentity.course_year2} onChange={(event) => setNewCourseIdentity((current) => ({ ...current, course_year2: event.target.value }))} placeholder={translate("families.create.year2")} />
                </div>
                <div className="mt-4">
                  <Textarea
                    className="min-h-[96px]"
                    value={newRawTypesInput}
                    onChange={(event) => setNewRawTypesInput(event.target.value)}
                    placeholder={translate("families.create.observedLabelsPlaceholder")}
                  />
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {newRawTypes.map((rawType) => (
                    <Badge key={rawType} tone="info">
                      {rawType}
                    </Badge>
                  ))}
                </div>
                <div className="mt-4">
                  <Button onClick={() => void createNewFamily()} disabled={busyCreate}>
                    {busyCreate ? translate("families.create.creating") : translate("families.create.create")}
                  </Button>
                </div>
              </div>
            ) : null}

            <div className="mt-4 space-y-3">
              {pagedFamilies.rows.length === 0 ? (
                <EmptyState title={translate("families.list.noFamilies")} description={translate("families.list.noFamiliesDescription")} />
              ) : (
                pagedFamilies.rows.map((family) => (
                  <button
                    key={family.id}
                    type="button"
                    onClick={() => setSelectedFamilyId(family.id)}
                    className={`block w-full rounded-[1.15rem] border p-4 text-left transition-all duration-300 ${
                      selectedFamily?.id === family.id
                        ? "border-[rgba(31,94,255,0.24)] bg-white shadow-[0_16px_32px_rgba(20,32,44,0.08)]"
                        : "border-line/80 bg-white/72 hover:-translate-y-0.5 hover:bg-white"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{family.course_display}</p>
                        <p className="mt-2 font-medium text-ink">{family.canonical_label}</p>
                        <div className="mt-3 flex flex-wrap gap-2 text-xs text-[#596270]">
                          <span>{translate("families.labels.observedLabel")}: {family.raw_types.length}</span>
                          <span>•</span>
                          <span>{translate("families.labels.activeEvents")}: {eventCountByFamilyId.get(family.id) || 0}</span>
                          <span>•</span>
                          <span>{translate("families.labels.pendingChanges")}: {translate("families.labels.unavailable")}</span>
                        </div>
                      </div>
                      <Badge tone={suggestionCountByFamilyId.get(family.id) ? "pending" : "info"}>
                        {suggestionCountByFamilyId.get(family.id) || 0}
                      </Badge>
                    </div>
                  </button>
                ))
              )}
            </div>

            <PaginationControls page={pagedFamilies.page} totalPages={pagedFamilies.totalPages} onPageChange={setFamilyPage} />
          </Card>

          <Card className="order-1 animate-surface-enter p-5 xl:order-2">
            {selectedFamily ? (
              <div>
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("families.list.selectedFamily")}</p>
                    <h3 className="mt-1 text-lg font-semibold text-ink">{selectedFamily.canonical_label}</h3>
                    <p className="mt-2 text-sm text-[#596270]">{selectedFamily.course_display}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="ghost" className="xl:hidden" onClick={() => setFamilyChooserOpen(true)}>
                      {translate("families.chooseFamily")}
                    </Button>
                    <Badge tone={selectedFamilyRawTypes.length >= 3 ? "pending" : "info"}>{translate("families.labels.observedLabel")}: {selectedFamilyRawTypes.length}</Badge>
                    <Badge tone="info">{translate("families.labels.activeEvents")}: {selectedFamilyEvents.length}</Badge>
                  </div>
                </div>

                <div className="mt-5 rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("families.list.canonicalRename")}</p>
                    </div>
                    <Button size="sm" onClick={() => void saveSelectedFamily()} disabled={busyFamilyId === selectedFamily.id}>
                      {busyFamilyId === selectedFamily.id ? translate("families.list.savingFamily") : translate("families.list.saveFamily")}
                    </Button>
                  </div>
                  <Input className="mt-4" value={draftLabel} onChange={(event) => setDraftLabel(event.target.value)} placeholder={translate("families.list.canonicalLabelPlaceholder")} />
                </div>

                <div className="mt-4 rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("families.list.observedLabels")}</p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {selectedFamilyRawTypes.length > 0 ? (
                      selectedFamilyRawTypes.map((rawType) => (
                        <Badge key={rawType.id} tone="info">
                          {rawType.raw_type}
                        </Badge>
                      ))
                    ) : (
                      <p className="text-sm text-[#596270]">{translate("families.list.noObservedLabels")}</p>
                    )}
                  </div>
                  <p className="mt-4 text-xs leading-5 text-[#6d7885]">
                    {translate("families.labels.pendingChanges")}: {translate("families.labels.unavailable")}
                  </p>
                </div>

                <div className="mt-4 rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("families.list.eventPreview")}</p>
                  <p className="mt-2 text-sm text-[#596270]">{translate("families.list.eventPreviewSummary")}</p>
                  <div className="mt-4 space-y-3">
                    {manualEvents.loading && !manualEvents.data ? (
                      <div className="rounded-[1rem] border border-dashed border-line/80 bg-white/65 p-4 text-sm text-[#596270]">
                        {translate("common.labels.loading", { label: translate("families.list.activeEvents") })}
                      </div>
                    ) : manualEvents.error ? (
                      <div className="rounded-[1rem] border border-[#efc4b5] bg-[#fff3ef] p-4 text-sm text-[#7f3d2a]">
                        Event preview is unavailable right now. {manualEvents.error}
                      </div>
                    ) : pagedEvents.rows.length === 0 ? (
                      <div className="rounded-[1rem] border border-dashed border-line/80 bg-white/65 p-4 text-sm text-[#596270]">
                        {translate("families.list.noEvents")}
                      </div>
                    ) : (
                      pagedEvents.rows.map((event) => (
                        <div key={event.entity_uid} className="rounded-[1rem] border border-line/80 bg-white/80 p-4">
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="font-medium text-ink">{familyEventTitle(event)}</p>
                              <p className="mt-1 text-sm text-[#596270]">
                                {formatSemanticDue(
                                  event.event as unknown as Record<string, unknown>,
                                  formatSemanticDue(event as unknown as Record<string, unknown>, translate("common.labels.notAvailable")),
                                )}
                              </p>
                            </div>
                            {event.ordinal != null ? <Badge tone="info">#{event.ordinal}</Badge> : null}
                          </div>
                          <div className="mt-3 flex flex-wrap gap-2 text-xs text-[#6d7885]">
                            {event.raw_type ? <span>{event.raw_type}</span> : null}
                            <span>{translate("sources.observability.updated")} {formatDateTime(event.updated_at)}</span>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                  {!manualEvents.loading && !manualEvents.error ? (
                    <PaginationControls page={pagedEvents.page} totalPages={pagedEvents.totalPages} onPageChange={setEventPage} />
                  ) : null}
                </div>
              </div>
            ) : (
              <EmptyState title={translate("families.list.noFamilySelected")} description={translate("families.list.noFamilySelectedDescription")} />
            )}
          </Card>
        </div>
      ) : null}

      <Sheet open={familyChooserOpen} onOpenChange={setFamilyChooserOpen}>
        <SheetContent side="bottom" className="overflow-y-auto xl:hidden">
          <SheetHeader>
            <div>
              <SheetTitle>{translate("families.chooseFamily")}</SheetTitle>
              <SheetDescription>{translate("families.list.chooseFamilySummary")}</SheetDescription>
            </div>
            <SheetDismissButton />
          </SheetHeader>
          <div className="mt-6 space-y-3">
            {visibleFamilies.map((family) => (
              <button
                key={family.id}
                type="button"
                onClick={() => {
                  setSelectedFamilyId(family.id);
                  setFamilyChooserOpen(false);
                }}
                className={`block w-full rounded-[1.15rem] border p-4 text-left transition-all duration-300 ${
                  selectedFamily?.id === family.id
                    ? "border-[rgba(31,94,255,0.24)] bg-white shadow-[0_16px_32px_rgba(20,32,44,0.08)]"
                    : "border-line/80 bg-white/72 hover:bg-white"
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{family.course_display}</p>
                    <p className="mt-2 font-medium text-ink">{family.canonical_label}</p>
                  </div>
                  <Badge tone="info">{translate("families.labels.observedLabel")}: {family.raw_types.length}</Badge>
                </div>
              </button>
            ))}
          </div>
        </SheetContent>
      </Sheet>

      {workspaceArea === "raw-types" ? (
        <Card className="animate-surface-enter p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("families.areas.observedLabels")}</p>
              <h3 className="mt-1 text-lg font-semibold text-ink">{translate("families.observed.title")}</h3>
              <p className="mt-2 text-sm text-[#596270]">{translate("families.observed.summary")}</p>
            </div>
            <Badge tone="info">{translate("families.counts.observedLabels", { count: visibleRawTypes.length })}</Badge>
          </div>

          <div className="mt-4 space-y-3">
            {pagedRawTypes.rows.length === 0 ? (
              <EmptyState title={translate("families.observed.noRows")} description={translate("families.observed.noRowsDescription")} />
            ) : (
              pagedRawTypes.rows.map((rawType) => {
                const targetFamilies = familyRows.filter((family) => family.course_display === rawType.course_display);
                const currentTarget = rawTypeTargets[rawType.id] || String(rawType.family_id);
                const eventKey = `${rawType.course_display}::${rawType.raw_type}`;
                const activeEvents = eventRowsByObservedLabel.get(eventKey) || [];
                const relatedSuggestions = suggestionCountByObservedLabel.get(eventKey) || 0;
                return (
                  <div key={rawType.id} className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
                    <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                      <div className="min-w-0 flex-1">
                        <p className="font-medium text-ink">{rawType.raw_type}</p>
                        <p className="mt-1 text-sm text-[#596270]">{rawType.course_display}</p>
                        <p className="mt-2 text-sm text-[#314051]">
                          {translate("families.observed.currentFamily", { label: familyLabelById[rawType.family_id] || translate("families.labels.unavailable") })}
                        </p>
                        <p className="mt-2 text-xs text-[#6d7885]">
                          {translate("families.observed.impactSummary", {
                            events: activeEvents.length,
                            suggestions: relatedSuggestions,
                          })}
                        </p>
                      </div>
                      <div className="flex w-full flex-col gap-2 sm:flex-row lg:w-auto">
                        <select
                          aria-label={translate("families.list.canonicalRename")}
                          className="h-11 min-w-[220px] rounded-2xl border border-line bg-white/85 px-4 text-sm text-ink outline-none transition focus:border-cobalt focus:bg-white"
                          value={currentTarget}
                          onChange={(event) => setRawTypeTargets((current) => ({ ...current, [rawType.id]: event.target.value }))}
                        >
                          {targetFamilies.map((family) => (
                            <option key={family.id} value={String(family.id)}>
                              {family.canonical_label}
                            </option>
                          ))}
                        </select>
                        <Button size="sm" disabled={busyRawTypeId === rawType.id || currentTarget === String(rawType.family_id)} onClick={() => previewMoveRawType(rawType)}>
                          {busyRawTypeId === rawType.id ? translate("families.observed.previewing") : translate("families.observed.previewMove")}
                        </Button>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          <PaginationControls page={pagedRawTypes.page} totalPages={pagedRawTypes.totalPages} onPageChange={setRawTypePage} />
        </Card>
      ) : null}

      {workspaceArea === "suggestions" ? (
        <Card className="animate-surface-enter p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("families.suggestions.title")}</p>
              <h3 className="mt-1 text-lg font-semibold text-ink">{translate("families.areas.suggestions")}</h3>
              <p className="mt-2 text-sm text-[#596270]">{translate("families.suggestions.summary")}</p>
            </div>
            <Badge tone={visibleSuggestions.length > 0 ? "pending" : "approved"}>{visibleSuggestions.length}</Badge>
          </div>

          <div className="mt-4 space-y-3">
            {pagedSuggestions.rows.length === 0 ? (
              <EmptyState title={translate("families.suggestions.noRows")} description={translate("families.suggestions.noRowsDescription")} />
            ) : (
              pagedSuggestions.rows.map((suggestion) => (
                <div key={suggestion.id} className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{suggestion.course_display}</p>
                      <div className="mt-2 flex items-center gap-2 text-sm font-medium text-ink">
                        <Sparkles className="h-4 w-4 text-cobalt" />
                        {suggestion.source_family_name || translate("families.suggestions.unknownFamily")} → {suggestion.suggested_family_name || translate("families.suggestions.suggestedFamily")}
                      </div>
                      <p className="mt-2 text-sm text-[#596270]">{suggestion.source_raw_type || translate("families.suggestions.unknownObservedLabel")} → {suggestion.suggested_raw_type || translate("families.suggestions.suggestedObservedLabel")}</p>
                    </div>
                    <Badge tone="info">{Math.round(suggestion.confidence * 100)}%</Badge>
                  </div>
                  {suggestion.evidence ? <p className="mt-4 text-sm leading-6 text-[#596270]">{suggestion.evidence}</p> : null}
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button size="sm" disabled={busySuggestionId === suggestion.id} onClick={() => void decideSuggestion(suggestion.id, "approve")}>
                      {busySuggestionId === suggestion.id ? translate("families.suggestions.applying") : translate("families.suggestions.approve")}
                    </Button>
                    <Button size="sm" variant="ghost" disabled={busySuggestionId === suggestion.id} onClick={() => void decideSuggestion(suggestion.id, "reject")}>
                      {translate("families.suggestions.reject")}
                    </Button>
                    <Button size="sm" variant="ghost" disabled={busySuggestionId === suggestion.id} onClick={() => void decideSuggestion(suggestion.id, "dismiss")}>
                      {translate("families.suggestions.dismiss")}
                    </Button>
                  </div>
                </div>
              ))
            )}
          </div>

          <PaginationControls page={pagedSuggestions.page} totalPages={pagedSuggestions.totalPages} onPageChange={setSuggestionPage} />
        </Card>
      ) : null}

      <Sheet open={Boolean(relinkPreviewRawType && relinkPreviewTargetFamily)} onOpenChange={(open) => (!open ? setRelinkPreview(null) : undefined)}>
        <SheetContent side="bottom" className="overflow-y-auto">
          <SheetHeader>
            <div>
              <SheetTitle>
                {relinkPreviewRawType && relinkPreviewTargetFamily
                  ? translate("families.observed.confirmMove", { label: relinkPreviewTargetFamily.canonical_label })
                  : translate("families.observed.reviewImpact")}
              </SheetTitle>
              <SheetDescription>{translate("families.observed.summary")}</SheetDescription>
            </div>
            <SheetDismissButton />
          </SheetHeader>
          {relinkPreviewRawType && relinkPreviewTargetFamily ? (
            <div className="mt-6 space-y-4">
              <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("families.labels.observedLabel")}</p>
                <p className="mt-2 text-base font-semibold text-ink">{relinkPreviewRawType.raw_type}</p>
                <p className="mt-3 text-sm text-[#314051]">
                  {translate("families.observed.currentFamily", { label: relinkPreviewCurrentFamily?.canonical_label || translate("families.labels.unavailable") })}
                </p>
                <p className="mt-2 text-sm text-[#314051]">
                  {translate("families.labels.canonicalFamily")}: {relinkPreviewTargetFamily.canonical_label}
                </p>
              </div>

              <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("families.observed.reviewImpact")}</p>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <div className="rounded-[1rem] border border-line/80 bg-white/80 p-3 text-sm text-[#314051]">
                    <p className="font-medium text-ink">{translate("families.labels.activeEvents")}</p>
                    <p className="mt-2">{relinkPreviewEvents.length}</p>
                  </div>
                  <div className="rounded-[1rem] border border-line/80 bg-white/80 p-3 text-sm text-[#314051]">
                    <p className="font-medium text-ink">{translate("families.areas.suggestions")}</p>
                    <p className="mt-2">{relinkPreviewSuggestionCount}</p>
                  </div>
                </div>
                <p className="mt-4 text-sm leading-6 text-[#596270]">{translate("families.observed.pendingChangesGap")}</p>
                <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("families.observed.futureImports")}</p>
              </div>

              <div className="rounded-[1.15rem] border border-line/80 bg-white/72 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("families.observed.sampleEvents")}</p>
                <div className="mt-4 space-y-3">
                  {relinkPreviewEvents.length === 0 ? (
                    <p className="text-sm text-[#596270]">{translate("families.observed.noSampleEvents")}</p>
                  ) : (
                    relinkPreviewEvents.map((event) => (
                      <div key={event.entity_uid} className="rounded-[1rem] border border-line/80 bg-white/80 p-4">
                        <p className="font-medium text-ink">{familyEventTitle(event)}</p>
                        <p className="mt-1 text-sm text-[#596270]">
                          {formatSemanticDue(event as unknown as Record<string, unknown>, translate("common.labels.notAvailable"))}
                        </p>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="flex flex-wrap gap-3">
                <Button disabled={busyRawTypeId === relinkPreviewRawType.id} onClick={() => void confirmMoveRawType()}>
                  {busyRawTypeId === relinkPreviewRawType.id ? translate("families.observed.previewing") : translate("families.observed.confirmMove", { label: relinkPreviewTargetFamily.canonical_label })}
                </Button>
                <Button variant="ghost" onClick={() => setRelinkPreview(null)}>
                  {translate("families.observed.keepInFamily", { label: relinkPreviewCurrentFamily?.canonical_label || translate("families.labels.canonicalFamily") })}
                </Button>
              </div>
            </div>
          ) : null}
        </SheetContent>
      </Sheet>
    </div>
  );
}
