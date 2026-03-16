"use client";

import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Plus, Search, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import {
  getCourseWorkItemFamilyStatus,
  listCourseWorkItemFamilies,
  listKnownCourseKeys,
  updateCourseWorkItemFamily,
} from "@/lib/api/users";
import { useApiResource } from "@/lib/use-api-resource";
import { formatCourseDisplay, formatDateTime } from "@/lib/presenters";
import type { CourseIdentity, CourseWorkItemFamily, CourseWorkItemFamilyStatus } from "@/lib/types";

function emptyCourseIdentity() {
  return { course_dept: "", course_number: "", course_suffix: "", course_quarter: "", course_year2: "" };
}

function normalizeCourseIdentityForm(identity: { course_dept: string; course_number: string; course_suffix: string; course_quarter: string; course_year2: string }) {
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

function compareFamilyRows(
  left: CourseWorkItemFamily,
  right: CourseWorkItemFamily,
  labels?: Record<number, string>
) {
  const courseCompare = left.course_display.localeCompare(right.course_display);
  if (courseCompare !== 0) return courseCompare;

  const leftLabel = (labels?.[left.id] || left.canonical_label || "").toLowerCase();
  const rightLabel = (labels?.[right.id] || right.canonical_label || "").toLowerCase();
  const labelCompare = leftLabel.localeCompare(rightLabel);
  if (labelCompare !== 0) return labelCompare;

  return left.id - right.id;
}

export function FamilyManagementPanel() {
  const families = useApiResource<CourseWorkItemFamily[]>(() => listCourseWorkItemFamilies(), []);
  const status = useApiResource<CourseWorkItemFamilyStatus>(() => getCourseWorkItemFamilyStatus(), []);
  const courses = useApiResource<{ courses: CourseIdentity[] }>(() => listKnownCourseKeys(), []);

  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [busyFamily, setBusyFamily] = useState<number | "new" | null>(null);
  const [draftCourseIdentities, setDraftCourseIdentities] = useState<Record<number, ReturnType<typeof emptyCourseIdentity>>>({});
  const [draftLabels, setDraftLabels] = useState<Record<number, string>>({});
  const [draftRawTypes, setDraftRawTypes] = useState<Record<number, string[]>>({});
  const [rawTypeInputs, setRawTypeInputs] = useState<Record<number, string>>({});
  const [courseQuery, setCourseQuery] = useState("");
  const [expandedCourses, setExpandedCourses] = useState<Record<string, boolean>>({});
  const [expandedFamilies, setExpandedFamilies] = useState<Record<number, boolean>>({});
  const deferredCourseQuery = useDeferredValue(courseQuery);

  useEffect(() => {
    if (!families.data) return;
    const nextCourseIdentities: Record<number, ReturnType<typeof emptyCourseIdentity>> = {};
    const nextLabels: Record<number, string> = {};
    const nextRawTypes: Record<number, string[]> = {};
    for (const family of families.data) {
      nextCourseIdentities[family.id] = {
        course_dept: family.course_dept,
        course_number: String(family.course_number),
        course_suffix: family.course_suffix || "",
        course_quarter: family.course_quarter || "",
        course_year2: family.course_year2 != null ? String(family.course_year2).padStart(2, "0") : "",
      };
      nextLabels[family.id] = family.canonical_label;
      nextRawTypes[family.id] = [...family.raw_types];
    }
    setDraftCourseIdentities(nextCourseIdentities);
    setDraftLabels(nextLabels);
    setDraftRawTypes(nextRawTypes);
  }, [families.data]);

  const familyRows = useMemo(
    () => [...(families.data || [])].sort((left, right) => compareFamilyRows(left, right, draftLabels)),
    [draftLabels, families.data]
  );
  const groupedFamilies = useMemo(() => {
    const groups = new Map<string, CourseWorkItemFamily[]>();
    for (const family of familyRows) {
      if (!groups.has(family.course_display)) groups.set(family.course_display, []);
      groups.get(family.course_display)!.push(family);
    }
    return Array.from(groups.entries());
  }, [familyRows]);
  const rawTypeCount = useMemo(() => familyRows.reduce((count, row) => count + row.raw_types.length, 0), [familyRows]);
  const filteredGroups = useMemo(() => {
    const query = deferredCourseQuery.trim().toLowerCase();
    if (!query) {
      return groupedFamilies;
    }
    return groupedFamilies
      .map(([courseKey, rows]) => {
        const matchedRows = rows.filter((row) => {
          const label = (draftLabels[row.id] || row.canonical_label || "").toLowerCase();
          const rawTypes = (draftRawTypes[row.id] || row.raw_types).join(" ").toLowerCase();
          return courseKey.toLowerCase().includes(query) || label.includes(query) || rawTypes.includes(query);
        });
        return [courseKey, matchedRows] as const;
      })
      .filter(([, rows]) => rows.length > 0);
  }, [deferredCourseQuery, draftLabels, draftRawTypes, groupedFamilies]);
  const visibleFamilyCount = useMemo(() => filteredGroups.reduce((count, [, rows]) => count + rows.length, 0), [filteredGroups]);

  async function refreshFamilies() {
    await Promise.all([families.refresh(), status.refresh(), courses.refresh()]);
  }

  async function saveFamily(familyId: number) {
    const canonicalLabel = (draftLabels[familyId] || "").trim();
    const rawTypes = draftRawTypes[familyId] || [];
    const identity = normalizeCourseIdentityForm(draftCourseIdentities[familyId] || emptyCourseIdentity());
    if (!identity || !canonicalLabel) return;
    setBusyFamily(familyId);
    setBanner(null);
    try {
      await updateCourseWorkItemFamily(familyId, { ...identity, canonical_label: canonicalLabel, raw_types: rawTypes });
      setBanner({ tone: "info", text: `Updated "${canonicalLabel}".` });
      await refreshFamilies();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to update family" });
    } finally {
      setBusyFamily(null);
    }
  }

  function addRawType(familyId: number) {
    const rawType = (rawTypeInputs[familyId] || "").trim();
    if (!rawType) return;
    const existing = new Set((draftRawTypes[familyId] || []).map((row) => row.toLowerCase()));
    if (existing.has(rawType.toLowerCase())) {
      setRawTypeInputs((prev) => ({ ...prev, [familyId]: "" }));
      return;
    }
    setDraftRawTypes((prev) => ({ ...prev, [familyId]: [...(prev[familyId] || []), rawType] }));
    setRawTypeInputs((prev) => ({ ...prev, [familyId]: "" }));
  }

  function removeRawType(familyId: number, rawType: string) {
    setDraftRawTypes((prev) => ({ ...prev, [familyId]: (prev[familyId] || []).filter((row) => row !== rawType) }));
  }

  function toggleCourseGroup(courseKey: string, nextExpanded: boolean) {
    setExpandedCourses((prev) => ({ ...prev, [courseKey]: nextExpanded }));
  }

  function toggleFamilyEditor(familyId: number, nextExpanded: boolean) {
    setExpandedFamilies((prev) => ({ ...prev, [familyId]: nextExpanded }));
  }

  if (families.loading || status.loading || courses.loading) return <LoadingState label="family workspace" />;
  if (families.error) return <ErrorState message={families.error} />;
  if (status.error) return <ErrorState message={status.error} />;
  if (courses.error) return <ErrorState message={courses.error} />;

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-[1.2rem] border border-line/80 bg-white/72 px-4 py-3 shadow-[var(--shadow-panel)] md:flex-row md:items-center md:justify-between">
        <div className="flex flex-wrap items-center gap-2 text-sm text-[#596270]">
          <span className="rounded-full bg-[rgba(20,32,44,0.06)] px-3 py-1.5 text-ink">{courses.data?.courses?.length || 0} courses</span>
          <span className="rounded-full bg-[rgba(20,32,44,0.06)] px-3 py-1.5 text-ink">{familyRows.length} families</span>
          <span className="rounded-full bg-[rgba(20,32,44,0.06)] px-3 py-1.5 text-ink">{rawTypeCount} raw types</span>
          <span className="rounded-full bg-[rgba(20,32,44,0.06)] px-3 py-1.5 text-ink">{visibleFamilyCount} visible</span>
        </div>
        <p className="text-sm text-[#596270]">Rebuild {status.data?.state || "idle"} · {formatDateTime(status.data?.last_rebuilt_at, "Never")}</p>
      </div>

      {banner ? (
        <Card className={banner.tone === "error" ? "border-[#efc4b5] bg-[#fff3ef] p-4" : "border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] p-4"}>
          <p className="text-sm text-[#314051]">{banner.text}</p>
        </Card>
      ) : null}

      {status.data?.last_error ? (
        <Card className="border-[#efc4b5] bg-[#fff3ef] p-4">
          <p className="text-sm text-[#7f3d2a]">{status.data.last_error}</p>
        </Card>
      ) : null}

      <div className="space-y-4">
          <Card className="bg-white/60 p-4">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Filter families</p>
              {courseQuery ? (
                <Button size="sm" variant="ghost" onClick={() => setCourseQuery("")}>
                  Clear filter
                </Button>
              ) : null}
            </div>
            <div className="mt-4 flex flex-wrap gap-3">
              <div className="relative min-w-0 flex-1">
                <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-[#7d8794]" />
                <Input
                  className="pl-11"
                  value={courseQuery}
                  onChange={(event) => setCourseQuery(event.target.value)}
                  placeholder="Filter by course, family label, or raw type"
                />
              </div>
              <Badge tone="info">{filteredGroups.length} course group{filteredGroups.length === 1 ? "" : "s"}</Badge>
            </div>
          </Card>

          {filteredGroups.length === 0 ? (
            <EmptyState title="No matching families" description="Try a broader filter, or add a new family from the Add Family page." />
          ) : (
            filteredGroups.map(([courseKey, rows], index) => {
              const isExpanded = deferredCourseQuery.trim() ? true : expandedCourses[courseKey] ?? index < 1;
              const groupRawTypeCount = rows.reduce((count, row) => count + (draftRawTypes[row.id] || row.raw_types).length, 0);

              return (
                <Card key={courseKey} className="overflow-hidden bg-white/60">
                  <button className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left" type="button" onClick={() => toggleCourseGroup(courseKey, !isExpanded)}>
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Course group</p>
                      <h4 className="mt-1 text-base font-semibold text-ink">{courseKey}</h4>
                      <p className="mt-1 text-sm text-[#596270]">{rows.length} family editor{rows.length === 1 ? "" : "s"} · {groupRawTypeCount} raw type{groupRawTypeCount === 1 ? "" : "s"}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge tone="info">{rows.length} families</Badge>
                      <Badge tone="approved">{groupRawTypeCount} raw</Badge>
                      {isExpanded ? <ChevronUp className="h-4 w-4 text-[#6d7885]" /> : <ChevronDown className="h-4 w-4 text-[#6d7885]" />}
                    </div>
                  </button>

                  {isExpanded ? (
                    <div className="border-t border-line/80 px-4 py-4">
                      <div className="space-y-4">
                        {rows.map((family) => (
                          <Card key={family.id} className="bg-white/78">
                            <button
                              type="button"
                              className="flex w-full items-center justify-between gap-4 px-4 py-4 text-left"
                              onClick={() => toggleFamilyEditor(family.id, !(expandedFamilies[family.id] ?? false))}
                            >
                              <div>
                                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Family #{family.id}</p>
                                <div className="mt-2 flex flex-wrap items-center gap-2">
                                  <h5 className="text-base font-semibold text-ink">{draftLabels[family.id] || family.canonical_label}</h5>
                                  <Badge tone="info">{(draftRawTypes[family.id] || []).length} raw type{(draftRawTypes[family.id] || []).length === 1 ? "" : "s"}</Badge>
                                  <Badge tone="default">Updated {formatDateTime(family.updated_at, "Recently")}</Badge>
                                </div>
                              </div>
                              <div className="flex items-center gap-2">
                                <Badge tone="info">{formatCourseDisplay(family as unknown as Record<string, unknown>)}</Badge>
                                {expandedFamilies[family.id] ? <ChevronUp className="h-4 w-4 text-[#6d7885]" /> : <ChevronDown className="h-4 w-4 text-[#6d7885]" />}
                              </div>
                            </button>

                            {expandedFamilies[family.id] ? (
                              <div className="border-t border-line/80 px-4 pb-4 pt-4">
                                <div className="flex flex-wrap items-start justify-between gap-4">
                                  <div className="text-sm text-[#596270]">
                                    Edit canonical label, course identity, and raw-type mapping.
                                  </div>
                                  <Button onClick={() => void saveFamily(family.id)} disabled={busyFamily === family.id}>
                                    {busyFamily === family.id ? "Saving..." : "Save"}
                                  </Button>
                                </div>

                                <div className="mt-4 grid gap-3 md:grid-cols-2">
                                  <div>
                                    <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]">Course display</label>
                                    <Input value={formatCourseDisplay(family as unknown as Record<string, unknown>)} disabled />
                                  </div>
                                  <div>
                                    <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]">Canonical label</label>
                                    <Input value={draftLabels[family.id] || ""} onChange={(event) => setDraftLabels((prev) => ({ ...prev, [family.id]: event.target.value }))} placeholder="Homework" />
                                  </div>
                                </div>

                                <div className="mt-4 grid gap-3 md:grid-cols-5">
                                  <Input value={draftCourseIdentities[family.id]?.course_dept || ""} onChange={(event) => setDraftCourseIdentities((prev) => ({ ...prev, [family.id]: { ...(prev[family.id] || emptyCourseIdentity()), course_dept: event.target.value } }))} placeholder="Dept" />
                                  <Input value={draftCourseIdentities[family.id]?.course_number || ""} onChange={(event) => setDraftCourseIdentities((prev) => ({ ...prev, [family.id]: { ...(prev[family.id] || emptyCourseIdentity()), course_number: event.target.value } }))} placeholder="Number" />
                                  <Input value={draftCourseIdentities[family.id]?.course_suffix || ""} onChange={(event) => setDraftCourseIdentities((prev) => ({ ...prev, [family.id]: { ...(prev[family.id] || emptyCourseIdentity()), course_suffix: event.target.value } }))} placeholder="Suffix" />
                                  <Input value={draftCourseIdentities[family.id]?.course_quarter || ""} onChange={(event) => setDraftCourseIdentities((prev) => ({ ...prev, [family.id]: { ...(prev[family.id] || emptyCourseIdentity()), course_quarter: event.target.value } }))} placeholder="Quarter" />
                                  <Input value={draftCourseIdentities[family.id]?.course_year2 || ""} onChange={(event) => setDraftCourseIdentities((prev) => ({ ...prev, [family.id]: { ...(prev[family.id] || emptyCourseIdentity()), course_year2: event.target.value } }))} placeholder="Year2" />
                                </div>

                                <div className="mt-4">
                                  <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Raw Types</p>
                                  <div className="mt-3 flex flex-wrap gap-2">
                                    {(draftRawTypes[family.id] || []).map((rawType) => (
                                      <span key={`${family.id}-${rawType}`} className="inline-flex items-center gap-2 rounded-full border border-line/80 bg-white px-3 py-1 text-sm text-[#314051]">
                                        {rawType}
                                        <button type="button" aria-label={`Remove raw type ${rawType}`} onClick={() => removeRawType(family.id, rawType)}>
                                          <X className="h-3.5 w-3.5" />
                                        </button>
                                      </span>
                                    ))}
                                  </div>
                                  <div className="mt-3 flex flex-wrap gap-3">
                                    <Input value={rawTypeInputs[family.id] || ""} onChange={(event) => setRawTypeInputs((prev) => ({ ...prev, [family.id]: event.target.value }))} placeholder="hw" className="max-w-sm" />
                                    <Button variant="ghost" onClick={() => addRawType(family.id)} disabled={!(rawTypeInputs[family.id] || "").trim()}>
                                      <Plus className="mr-2 h-4 w-4" />
                                      Add raw type
                                    </Button>
                                  </div>
                                </div>
                              </div>
                            ) : null}
                          </Card>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </Card>
              );
            })
          )}
      </div>
    </div>
  );
}
