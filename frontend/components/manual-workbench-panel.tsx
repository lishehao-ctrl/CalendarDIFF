"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Plus, Trash2 } from "lucide-react";
import { EmptyState, ErrorState } from "@/components/data-states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetDismissButton, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { WorkbenchLoadingShell } from "@/components/workbench-loading-shell";
import {
  createManualEvent,
  deleteManualEvent,
  listManualEvents,
  manualEventsCacheKey,
  updateManualEvent,
} from "@/lib/api/manual";
import { familiesListCacheKey, listFamilies } from "@/lib/api/families";
import { translate } from "@/lib/i18n/runtime";
import { useResponsiveTier } from "@/lib/use-responsive-tier";
import { useApiResource } from "@/lib/use-api-resource";
import { formatDateTime, formatSemanticDue, formatStatusLabel } from "@/lib/presenters";
import { workbenchQueueRowClassName, workbenchStateSurfaceClassName, workbenchSupportPanelClassName } from "@/lib/workbench-styles";
import type { CourseWorkItemFamily, ManualEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

type Banner = {
  tone: "info" | "error";
  text: string;
} | null;

type EventFormState = {
  familyId: string;
  eventName: string;
  rawType: string;
  ordinal: string;
  dueDate: string;
  dueTime: string;
  timePrecision: "date_only" | "datetime";
  reason: string;
};

const selectClassName =
  "h-11 w-full rounded-2xl border border-line bg-white/80 px-4 text-sm text-ink outline-none transition focus:border-cobalt focus:bg-white";

function emptyEventForm(familyId = ""): EventFormState {
  return {
    familyId,
    eventName: "",
    rawType: "",
    ordinal: "",
    dueDate: "",
    dueTime: "",
    timePrecision: "date_only",
    reason: "",
  };
}

function normalizeEventForm(form: EventFormState) {
  const familyId = Number(form.familyId);
  const eventName = form.eventName.trim();
  const dueDate = form.dueDate.trim();
  if (!Number.isFinite(familyId) || familyId <= 0 || !eventName || !dueDate) {
    return null;
  }
  const ordinal = form.ordinal.trim();
  const nextOrdinal = ordinal ? Number(ordinal) : null;
  return {
    family_id: familyId,
    event_name: eventName,
    raw_type: form.rawType.trim() || null,
    ordinal: ordinal && Number.isFinite(nextOrdinal) ? nextOrdinal : null,
    due_date: dueDate,
    due_time: form.timePrecision === "date_only" ? null : form.dueTime.trim() || null,
    time_precision: form.timePrecision,
    reason: form.reason.trim() || null,
  };
}

function eventSummaryLabel(event: ManualEvent) {
  const baseLabel = [event.course_display, event.family_name].filter(Boolean).join(" · ");
  const numberLabel = event.ordinal ?? event.event?.event_display.ordinal ?? null;
  if (baseLabel && numberLabel) {
    return `${baseLabel} #${numberLabel}`;
  }
  return baseLabel || event.event_name || event.entity_uid;
}

function compareFamilyRows(left: CourseWorkItemFamily, right: CourseWorkItemFamily) {
  const courseCompare = left.course_display.localeCompare(right.course_display);
  if (courseCompare !== 0) return courseCompare;

  const labelCompare = (left.canonical_label || "").toLowerCase().localeCompare((right.canonical_label || "").toLowerCase());
  if (labelCompare !== 0) return labelCompare;

  return left.id - right.id;
}

function FieldLabel({ htmlFor, children }: { htmlFor?: string; children: React.ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]">
      {children}
    </label>
  );
}

export function ManualWorkbenchPanel() {
  const { isMobile, isDesktop, isTabletWide } = useResponsiveTier();
  const families = useApiResource<CourseWorkItemFamily[]>(() => listFamilies(), [], [], {
    cacheKey: familiesListCacheKey(),
  });
  const manualEvents = useApiResource<ManualEvent[]>(() => listManualEvents(), [], [], {
    cacheKey: manualEventsCacheKey(),
  });

  const [banner, setBanner] = useState<Banner>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [selectedCourseKey, setSelectedCourseKey] = useState("all");
  const [selectedFamilyId, setSelectedFamilyId] = useState("all");
  const [addCourseKey, setAddCourseKey] = useState("");
  const [expandedEventUid, setExpandedEventUid] = useState<string | null>(null);
  const [editEventForm, setEditEventForm] = useState<EventFormState>(emptyEventForm());
  const [addEventForm, setAddEventForm] = useState<EventFormState>(emptyEventForm());
  const [busyEvent, setBusyEvent] = useState<"save" | "delete" | "create" | null>(null);

  const familyRows = useMemo(() => [...(families.data || [])].sort(compareFamilyRows), [families.data]);
  const eventRows = useMemo(() => manualEvents.data || [], [manualEvents.data]);
  const courseOptions = useMemo(() => {
    const values = new Set<string>();
    for (const family of familyRows) values.add(family.course_display);
    for (const event of eventRows) values.add(event.course_display);
    return Array.from(values).sort((a, b) => a.localeCompare(b));
  }, [eventRows, familyRows]);
  const familyCourseOptions = useMemo(() => Array.from(new Set(familyRows.map((row) => row.course_display))).sort((a, b) => a.localeCompare(b)), [familyRows]);
  const familiesByCourse = useMemo(() => {
    const next = new Map<string, CourseWorkItemFamily[]>();
    for (const family of familyRows) {
      if (!next.has(family.course_display)) next.set(family.course_display, []);
      next.get(family.course_display)!.push(family);
    }
    return next;
  }, [familyRows]);
  const filteredEventRows = useMemo(() => {
    return [...eventRows]
      .filter((event) => {
        if (selectedCourseKey !== "all" && event.course_display !== selectedCourseKey) return false;
        if (selectedFamilyId !== "all" && event.family_id !== Number(selectedFamilyId)) return false;
        return true;
      })
      .sort((a, b) => {
        const labelCompare = eventSummaryLabel(a).localeCompare(eventSummaryLabel(b));
        if (labelCompare !== 0) return labelCompare;
        return (a.entity_uid || "").localeCompare(b.entity_uid || "");
      });
  }, [eventRows, selectedCourseKey, selectedFamilyId]);
  const eventFilterFamilies = useMemo(() => {
    if (!selectedCourseKey || selectedCourseKey === "all") return familyRows;
    return familiesByCourse.get(selectedCourseKey) || [];
  }, [familiesByCourse, familyRows, selectedCourseKey]);
  const addFormFamilies = useMemo(() => {
    if (!addCourseKey) return familyRows;
    return familiesByCourse.get(addCourseKey) || [];
  }, [addCourseKey, familiesByCourse, familyRows]);
  const courseCount = familyCourseOptions.length;
  const showSplitWorkbench = !isMobile;
  const selectedEvent = useMemo(
    () => filteredEventRows.find((event) => event.entity_uid === expandedEventUid) || filteredEventRows[0] || null,
    [expandedEventUid, filteredEventRows],
  );

  useEffect(() => {
    if (!familyRows.length) {
      setSelectedCourseKey("all");
      setAddCourseKey("");
      setSelectedFamilyId("all");
      setAddEventForm((prev) => ({ ...prev, familyId: "" }));
      return;
    }

    const nextCourseKey = selectedCourseKey === "all" || courseOptions.includes(selectedCourseKey) ? selectedCourseKey : "all";
    const nextAddCourseKey = familyCourseOptions.includes(addCourseKey) ? addCourseKey : familyCourseOptions[0];

    if (nextCourseKey !== selectedCourseKey) setSelectedCourseKey(nextCourseKey);
    if (nextAddCourseKey && nextAddCourseKey !== addCourseKey) setAddCourseKey(nextAddCourseKey);
  }, [addCourseKey, courseOptions, familyCourseOptions, familyRows.length, selectedCourseKey]);

  useEffect(() => {
    const rows = eventFilterFamilies;
    setSelectedFamilyId((prev) => {
      if (prev === "all" || rows.some((row) => String(row.id) === prev)) return prev;
      return "all";
    });
  }, [eventFilterFamilies]);

  useEffect(() => {
    const rows = addFormFamilies;
    setAddEventForm((prev) => {
      if (prev.familyId && rows.some((row) => String(row.id) === prev.familyId)) {
        return prev;
      }
      return { ...prev, familyId: rows[0] ? String(rows[0].id) : "" };
    });
  }, [addFormFamilies]);

  useEffect(() => {
    if (!filteredEventRows.length) {
      setExpandedEventUid(null);
      return;
    }
    if (!expandedEventUid || !filteredEventRows.some((event) => event.entity_uid === expandedEventUid)) {
      openEvent(filteredEventRows[0]);
    }
  }, [expandedEventUid, filteredEventRows]);

  function clearExpandedEvent() {
    setExpandedEventUid(null);
    setEditEventForm(emptyEventForm());
  }

  function openEvent(event: ManualEvent) {
    setExpandedEventUid(event.entity_uid);
    setEditEventForm({
      familyId: event.family_id ? String(event.family_id) : "",
      eventName: event.event_name || "",
      rawType: event.raw_type || "",
      ordinal: event.ordinal ? String(event.ordinal) : "",
      dueDate: event.due_date || "",
      dueTime: event.time_precision === "date_only" ? "" : (event.due_time || "").slice(0, 5),
      timePrecision: event.time_precision === "date_only" ? "date_only" : "datetime",
      reason: "",
    });
    setBanner(null);
  }

  async function submitEditedEvent() {
    if (!expandedEventUid) return;
    const payload = normalizeEventForm(editEventForm);
    if (!payload) {
      setBanner({ tone: "error", text: translate("manual.validation") });
      return;
    }
    setBusyEvent("save");
    setBanner(null);
    try {
      await updateManualEvent(expandedEventUid, payload);
      setBanner({ tone: "info", text: translate("manual.eventUpdated") });
      await manualEvents.refresh();
      clearExpandedEvent();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("manual.saveFailed") });
    } finally {
      setBusyEvent(null);
    }
  }

  async function submitNewEvent() {
    const payload = normalizeEventForm(addEventForm);
    if (!payload) {
      setBanner({ tone: "error", text: translate("manual.validation") });
      return;
    }
    setBusyEvent("create");
    setBanner(null);
    try {
      await createManualEvent(payload);
      setBanner({ tone: "info", text: translate("manual.eventAdded") });
      await manualEvents.refresh();
      setAddOpen(false);
      setSelectedCourseKey(addCourseKey);
      setSelectedFamilyId(String(payload.family_id));
      setAddEventForm((prev) => emptyEventForm(prev.familyId || String(payload.family_id)));
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("manual.addFailed") });
    } finally {
      setBusyEvent(null);
    }
  }

  async function removeEvent(event: ManualEvent) {
    if (typeof window !== "undefined" && !window.confirm(translate("manual.deleteConfirm", { label: eventSummaryLabel(event) }))) {
      return;
    }
    setBusyEvent("delete");
    setBanner(null);
    try {
      await deleteManualEvent(event.entity_uid, "manual cleanup");
      setBanner({ tone: "info", text: translate("manual.eventDeleted") });
      await manualEvents.refresh();
      if (expandedEventUid === event.entity_uid) {
        clearExpandedEvent();
      }
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("manual.deleteFailed") });
    } finally {
      setBusyEvent(null);
    }
  }

  if (families.loading || manualEvents.loading) return <WorkbenchLoadingShell variant="manual" />;
  if (families.error) return <ErrorState message={families.error} />;
  if (manualEvents.error) return <ErrorState message={manualEvents.error} />;

  return (
    <div className="space-y-6">
      {banner ? (
        <Card className={workbenchStateSurfaceClassName(banner.tone === "error" ? "error" : "info", "p-4")}>
          <p className={banner.tone === "error" ? "text-sm text-[#7f3d2a]" : "text-sm text-[#314051]"}>{banner.text}</p>
        </Card>
      ) : null}

      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <p className="text-sm text-[#596270]">
          {translate("common.labels.eventsCount", { count: eventRows.length })} · {translate("common.labels.coursesCount", { count: courseCount })}
        </p>
        <Button size="sm" variant={addOpen ? "secondary" : "ghost"} onClick={() => setAddOpen((current) => !current)}>
          <Plus className="mr-2 h-4 w-4" />
          {addOpen ? translate("common.actions.hideAddForm") : translate("manual.addButton")}
        </Button>
      </div>

      <Sheet open={addOpen} onOpenChange={setAddOpen}>
        <SheetContent side="bottom" className="overflow-y-auto">
          <SheetHeader>
            <div>
              <SheetTitle>{translate("manual.addSheetTitle")}</SheetTitle>
              <SheetDescription>{translate("manual.addSheetSummary")}</SheetDescription>
            </div>
            <SheetDismissButton />
          </SheetHeader>
          <div className="mt-6 space-y-4">
            {!familyRows.length ? (
              <EmptyState title={translate("manual.noFamiliesTitle")} description={translate("manual.noFamiliesDescription")} />
            ) : (
              <>
                <Card className="p-5">
                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <FieldLabel htmlFor="manual-add-course">{translate("manual.course")}</FieldLabel>
                      <select
                        id="manual-add-course"
                        value={addCourseKey}
                        onChange={(event) => setAddCourseKey(event.target.value)}
                        className={selectClassName}
                      >
                        {familyCourseOptions.map((course) => (
                          <option key={course} value={course}>
                            {course}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <FieldLabel htmlFor="manual-add-family">{translate("manual.family")}</FieldLabel>
                      <select
                        id="manual-add-family"
                        value={addEventForm.familyId}
                        onChange={(event) => setAddEventForm((prev) => ({ ...prev, familyId: event.target.value }))}
                        className={selectClassName}
                      >
                        <option value="">{translate("manual.selectFamily")}</option>
                        {addFormFamilies.map((family) => (
                          <option key={family.id} value={family.id}>
                            {family.canonical_label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                </Card>

                <Card className="p-5">
                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <FieldLabel htmlFor="manual-add-name">{translate("manual.eventName")}</FieldLabel>
                      <Input
                        id="manual-add-name"
                        value={addEventForm.eventName}
                        onChange={(event) => setAddEventForm((prev) => ({ ...prev, eventName: event.target.value }))}
                        placeholder={translate("manual.sampleEventName")}
                      />
                    </div>
                    <div>
                      <FieldLabel htmlFor="manual-add-raw-type">{translate("manual.rawType")}</FieldLabel>
                      <Input
                        id="manual-add-raw-type"
                        value={addEventForm.rawType}
                        onChange={(event) => setAddEventForm((prev) => ({ ...prev, rawType: event.target.value }))}
                        placeholder={translate("manual.sampleObservedLabel")}
                      />
                    </div>
                    <div>
                      <FieldLabel htmlFor="manual-add-ordinal">{translate("manual.number")}</FieldLabel>
                      <Input
                        id="manual-add-ordinal"
                        value={addEventForm.ordinal}
                        onChange={(event) => setAddEventForm((prev) => ({ ...prev, ordinal: event.target.value }))}
                        placeholder={translate("manual.sampleOrdinal")}
                      />
                    </div>
                    <div>
                      <FieldLabel htmlFor="manual-add-date">{translate("manual.dueDate")}</FieldLabel>
                      <Input id="manual-add-date" type="date" value={addEventForm.dueDate} onChange={(event) => setAddEventForm((prev) => ({ ...prev, dueDate: event.target.value }))} />
                    </div>
                    <div>
                      <FieldLabel htmlFor="manual-add-precision">{translate("manual.timeMode")}</FieldLabel>
                      <select
                        id="manual-add-precision"
                        value={addEventForm.timePrecision}
                        onChange={(event) => setAddEventForm((prev) => ({ ...prev, timePrecision: event.target.value as "date_only" | "datetime" }))}
                        className={selectClassName}
                      >
                        <option value="date_only">{formatStatusLabel("date_only")}</option>
                        <option value="datetime">{formatStatusLabel("datetime")}</option>
                      </select>
                    </div>
                    {addEventForm.timePrecision === "datetime" ? (
                      <div>
                        <FieldLabel htmlFor="manual-add-time">{translate("manual.dueTime")}</FieldLabel>
                        <Input id="manual-add-time" type="time" value={addEventForm.dueTime} onChange={(event) => setAddEventForm((prev) => ({ ...prev, dueTime: event.target.value }))} />
                      </div>
                    ) : null}
                  </div>
                  <div className="mt-4">
                    <FieldLabel htmlFor="manual-add-reason">{translate("manual.reason")}</FieldLabel>
                    <Textarea id="manual-add-reason" value={addEventForm.reason} onChange={(event) => setAddEventForm((prev) => ({ ...prev, reason: event.target.value }))} placeholder={translate("manual.reasonPlaceholder")} className="min-h-[92px]" />
                  </div>
                  <div className="mt-4 flex justify-end">
                    <Button onClick={() => void submitNewEvent()} disabled={busyEvent === "create" || !addFormFamilies.length}>
                      <Plus className="mr-2 h-4 w-4" />
                      {busyEvent === "create" ? translate("manual.addButtonBusy") : translate("manual.addButton")}
                    </Button>
                  </div>
                </Card>
              </>
            )}
          </div>
        </SheetContent>
      </Sheet>

      <div className="space-y-4">
        <Card className="p-5">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] xl:items-end">
            <div>
              <FieldLabel htmlFor="manual-events-course">{translate("manual.course")}</FieldLabel>
              <select
                id="manual-events-course"
                value={selectedCourseKey}
                onChange={(event) => setSelectedCourseKey(event.target.value)}
                className={selectClassName}
              >
                <option value="all">{translate("families.allCourses")}</option>
                {courseOptions.map((course) => (
                  <option key={course} value={course}>
                    {course}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <FieldLabel htmlFor="manual-events-family">{translate("manual.family")}</FieldLabel>
              <select
                id="manual-events-family"
                value={selectedFamilyId}
                onChange={(event) => setSelectedFamilyId(event.target.value)}
                className={selectClassName}
              >
                <option value="all">{translate("manual.allFamilies")}</option>
                {eventFilterFamilies.map((family) => (
                  <option key={family.id} value={family.id}>
                    {family.canonical_label}
                  </option>
                ))}
              </select>
            </div>
            <div className="pb-2 text-sm text-[#596270] md:col-span-2 xl:col-span-1">{translate("common.labels.eventsCount", { count: filteredEventRows.length })}</div>
          </div>
        </Card>

        {filteredEventRows.length === 0 ? (
          <EmptyState title={translate("manual.noEventsTitle")} description={translate("manual.listEmpty")} />
        ) : (
          <>
          {showSplitWorkbench ? (
          <div className={cn("grid items-start gap-4", isDesktop ? "md:grid-cols-[320px_minmax(0,1fr)]" : isTabletWide ? "lg:grid-cols-[320px_minmax(0,1fr)]" : "md:grid-cols-[280px_minmax(0,1fr)]")}>
            <Card className="self-start p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("manual.heroEyebrow")}</p>
              <h3 className="mt-1 text-lg font-semibold text-ink">{translate("manual.heroTitle")}</h3>
              <div className="mt-4 space-y-3">
                {filteredEventRows.map((event) => (
                  <button
                    key={event.entity_uid}
                    type="button"
                    onClick={() => openEvent(event)}
                    className={workbenchQueueRowClassName({
                      selected: selectedEvent?.entity_uid === event.entity_uid,
                      className: "block w-full px-4 py-3 text-left",
                    })}
                  >
                    <p className="truncate text-sm font-medium text-ink">{eventSummaryLabel(event)}</p>
                    <p className="mt-1 text-xs text-[#6d7885]">{formatSemanticDue(event as unknown as Record<string, unknown>, translate("common.labels.noDueDate"))}</p>
                  </button>
                ))}
              </div>
            </Card>

            {selectedEvent ? (
              <div className={cn("space-y-4", isDesktop ? "xl:grid xl:grid-cols-[minmax(0,1fr)_240px] xl:items-start xl:gap-4 xl:space-y-0" : "")}>
                <Card className="p-5">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("manual.identity")}</p>
                      <h3 className="mt-1 text-lg font-semibold text-ink">{eventSummaryLabel(selectedEvent)}</h3>
                    </div>
                    <Button size="sm" variant="ghost" onClick={() => void removeEvent(selectedEvent)} disabled={busyEvent === "delete"}>
                      <Trash2 className="mr-1.5 h-4 w-4" />
                      {translate("common.actions.delete")}
                    </Button>
                  </div>
                  <div className="mt-5 grid gap-4 lg:grid-cols-2">
                    <div className={workbenchSupportPanelClassName("quiet", "p-4")}>
                      <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("manual.identity")}</p>
                      <div className="mt-4 space-y-4">
                        <div>
                          <FieldLabel htmlFor={`workbench-event-family-${selectedEvent.entity_uid}`}>{translate("manual.family")}</FieldLabel>
                          <select
                            id={`workbench-event-family-${selectedEvent.entity_uid}`}
                            value={editEventForm.familyId}
                            onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, familyId: nextEvent.target.value }))}
                            className={selectClassName}
                          >
                            <option value="">{translate("manual.selectFamily")}</option>
                            {familyRows.map((family) => (
                              <option key={family.id} value={family.id}>
                                {family.course_display} - {family.canonical_label}
                              </option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <FieldLabel htmlFor={`workbench-event-name-${selectedEvent.entity_uid}`}>{translate("manual.eventName")}</FieldLabel>
                          <Input id={`workbench-event-name-${selectedEvent.entity_uid}`} value={editEventForm.eventName} onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, eventName: nextEvent.target.value }))} />
                        </div>
                        <div>
                          <FieldLabel htmlFor={`workbench-event-raw-${selectedEvent.entity_uid}`}>{translate("manual.rawType")}</FieldLabel>
                          <Input id={`workbench-event-raw-${selectedEvent.entity_uid}`} value={editEventForm.rawType} onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, rawType: nextEvent.target.value }))} />
                        </div>
                        <div>
                          <FieldLabel htmlFor={`workbench-event-ordinal-${selectedEvent.entity_uid}`}>{translate("manual.number")}</FieldLabel>
                          <Input id={`workbench-event-ordinal-${selectedEvent.entity_uid}`} value={editEventForm.ordinal} onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, ordinal: nextEvent.target.value }))} placeholder="3" />
                        </div>
                      </div>
                    </div>

                    <div className={workbenchSupportPanelClassName("quiet", "p-4")}>
                      <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("manual.timing")}</p>
                      <div className="mt-4 space-y-4">
                        <div>
                          <FieldLabel htmlFor={`workbench-event-date-${selectedEvent.entity_uid}`}>{translate("manual.dueDate")}</FieldLabel>
                          <Input id={`workbench-event-date-${selectedEvent.entity_uid}`} type="date" value={editEventForm.dueDate} onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, dueDate: nextEvent.target.value }))} />
                        </div>
                        <div>
                          <FieldLabel htmlFor={`workbench-event-precision-${selectedEvent.entity_uid}`}>{translate("manual.timeMode")}</FieldLabel>
                          <select
                            id={`workbench-event-precision-${selectedEvent.entity_uid}`}
                            value={editEventForm.timePrecision}
                            onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, timePrecision: nextEvent.target.value as "date_only" | "datetime" }))}
                            className={selectClassName}
                          >
                            <option value="date_only">{formatStatusLabel("date_only")}</option>
                            <option value="datetime">{formatStatusLabel("datetime")}</option>
                          </select>
                        </div>
                        {editEventForm.timePrecision === "datetime" ? (
                          <div>
                            <FieldLabel htmlFor={`workbench-event-time-${selectedEvent.entity_uid}`}>{translate("manual.dueTime")}</FieldLabel>
                            <Input id={`workbench-event-time-${selectedEvent.entity_uid}`} type="time" value={editEventForm.dueTime} onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, dueTime: nextEvent.target.value }))} />
                          </div>
                        ) : null}
                        <div>
                          <FieldLabel htmlFor={`workbench-event-reason-${selectedEvent.entity_uid}`}>{translate("manual.reason")}</FieldLabel>
                          <Textarea
                            id={`workbench-event-reason-${selectedEvent.entity_uid}`}
                            value={editEventForm.reason}
                            onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, reason: nextEvent.target.value }))}
                            placeholder={translate("manual.reasonPlaceholder")}
                            className="min-h-[92px]"
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="mt-4 flex items-center justify-between gap-3">
                    <p className="text-sm text-[#596270]">
                      {translate("manual.updatedMeta", {
                        due: formatSemanticDue(selectedEvent as unknown as Record<string, unknown>, translate("common.labels.noDueDate")),
                        time: formatDateTime(selectedEvent.updated_at, translate("common.labels.recent")),
                      })}
                    </p>
                    <Button size="sm" onClick={() => void submitEditedEvent()} disabled={busyEvent === "save"}>
                      {busyEvent === "save" ? `${translate("common.actions.save")}...` : translate("common.actions.save")}
                    </Button>
                  </div>
                </Card>

                {isDesktop ? (
                  <Card className="hidden self-start p-4 xl:block">
                    <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("manual.heroEyebrow")}</p>
                    <div className={workbenchSupportPanelClassName("quiet", "mt-3 p-4")}>
                      <p className="text-sm leading-6 text-[#596270]">{translate("manual.heroSummary")}</p>
                    </div>
                    <div className="mt-4">
                      <Button size="sm" variant={addOpen ? "secondary" : "ghost"} onClick={() => setAddOpen((current) => !current)}>
                        <Plus className="mr-2 h-4 w-4" />
                        {addOpen ? translate("common.actions.hideAddForm") : translate("manual.addButton")}
                      </Button>
                    </div>
                  </Card>
                ) : (
                  <Card className="p-4">
                    <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("manual.heroEyebrow")}</p>
                    <div className={workbenchSupportPanelClassName("quiet", "mt-3 p-4")}>
                      <p className="text-sm leading-6 text-[#596270]">{translate("manual.heroSummary")}</p>
                    </div>
                    <div className="mt-4">
                      <Button size="sm" variant={addOpen ? "secondary" : "ghost"} onClick={() => setAddOpen((current) => !current)}>
                        <Plus className="mr-2 h-4 w-4" />
                        {addOpen ? translate("common.actions.hideAddForm") : translate("manual.addButton")}
                      </Button>
                    </div>
                  </Card>
                )}
              </div>
            ) : null}
          </div>
          ) : null}

          {isMobile ? (
          <Card className="p-4">
            <div className="space-y-3">
              {filteredEventRows.map((event) => {
                const expanded = expandedEventUid === event.entity_uid;
                return (
                  <div
                    key={event.entity_uid}
                    className={workbenchQueueRowClassName({
                      selected: expanded,
                      className: "px-4 py-3",
                    })}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-ink">{eventSummaryLabel(event)}</p>
                      </div>
                      <Button size="sm" variant="ghost" onClick={() => (expanded ? clearExpandedEvent() : openEvent(event))}>
                        {expanded ? translate("manual.close") : translate("manual.open")}
                        {expanded ? <ChevronUp className="ml-2 h-4 w-4" /> : <ChevronDown className="ml-2 h-4 w-4" />}
                      </Button>
                    </div>

                    {expanded ? (
                      <div className="mt-4 border-t border-line/70 pt-4">
                        <div className="grid gap-4 sm:grid-cols-2">
                          <div className={workbenchSupportPanelClassName("quiet", "p-4")}>
                            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("manual.identity")}</p>
                            <div className="mt-4 space-y-4">
                              <div>
                                <FieldLabel htmlFor={`event-family-${event.entity_uid}`}>{translate("manual.family")}</FieldLabel>
                                <select
                                  id={`event-family-${event.entity_uid}`}
                                  value={editEventForm.familyId}
                                  onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, familyId: nextEvent.target.value }))}
                                  className={selectClassName}
                                >
                                  <option value="">{translate("manual.selectFamily")}</option>
                                  {familyRows.map((family) => (
                                    <option key={family.id} value={family.id}>
                                      {family.course_display} - {family.canonical_label}
                                    </option>
                                  ))}
                                </select>
                              </div>
                              <div>
                                <FieldLabel htmlFor={`event-name-${event.entity_uid}`}>{translate("manual.eventName")}</FieldLabel>
                                <Input
                                  id={`event-name-${event.entity_uid}`}
                                  value={editEventForm.eventName}
                                  onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, eventName: nextEvent.target.value }))}
                                />
                              </div>
                              <div>
                                <FieldLabel htmlFor={`event-raw-type-${event.entity_uid}`}>{translate("manual.rawType")}</FieldLabel>
                                <Input
                                  id={`event-raw-type-${event.entity_uid}`}
                                  value={editEventForm.rawType}
                                  onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, rawType: nextEvent.target.value }))}
                                />
                              </div>
                              <div>
                                <FieldLabel htmlFor={`event-ordinal-${event.entity_uid}`}>{translate("manual.number")}</FieldLabel>
                                <Input
                                  id={`event-ordinal-${event.entity_uid}`}
                                  value={editEventForm.ordinal}
                                  onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, ordinal: nextEvent.target.value }))}
                                  placeholder="3"
                                />
                              </div>
                            </div>
                          </div>

                          <div className={workbenchSupportPanelClassName("quiet", "p-4")}>
                            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("manual.timing")}</p>
                            <div className="mt-4 space-y-4">
                              <div>
                                <FieldLabel htmlFor={`event-date-${event.entity_uid}`}>{translate("manual.dueDate")}</FieldLabel>
                                <Input
                                  id={`event-date-${event.entity_uid}`}
                                  type="date"
                                  value={editEventForm.dueDate}
                                  onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, dueDate: nextEvent.target.value }))}
                                />
                              </div>
                              <div>
                                <FieldLabel htmlFor={`event-precision-${event.entity_uid}`}>{translate("manual.timeMode")}</FieldLabel>
                                <select
                                  id={`event-precision-${event.entity_uid}`}
                                  value={editEventForm.timePrecision}
                                  onChange={(nextEvent) =>
                                    setEditEventForm((prev) => ({ ...prev, timePrecision: nextEvent.target.value as "date_only" | "datetime" }))
                                  }
                                  className={selectClassName}
                                >
                                  <option value="date_only">{formatStatusLabel("date_only")}</option>
                                  <option value="datetime">{formatStatusLabel("datetime")}</option>
                                </select>
                              </div>
                              {editEventForm.timePrecision === "datetime" ? (
                                <div>
                                  <FieldLabel htmlFor={`event-time-${event.entity_uid}`}>{translate("manual.dueTime")}</FieldLabel>
                                  <Input
                                    id={`event-time-${event.entity_uid}`}
                                    type="time"
                                    value={editEventForm.dueTime}
                                    onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, dueTime: nextEvent.target.value }))}
                                  />
                                </div>
                              ) : null}
                            </div>
                          </div>

                          <div className={workbenchSupportPanelClassName("quiet", "p-4 sm:col-span-2")}>
                            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("manual.auditNote")}</p>
                            <div className="mt-4">
                              <FieldLabel htmlFor={`event-reason-${event.entity_uid}`}>{translate("manual.reason")}</FieldLabel>
                              <Textarea
                                id={`event-reason-${event.entity_uid}`}
                                value={editEventForm.reason}
                                onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, reason: nextEvent.target.value }))}
                                placeholder={translate("manual.reasonPlaceholder")}
                                className="min-h-[92px]"
                              />
                            </div>
                          </div>
                        </div>
                        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                          <p className="text-sm text-[#596270]">
                            {translate("manual.updatedMeta", {
                              due: formatSemanticDue(event as unknown as Record<string, unknown>, translate("common.labels.noDueDate")),
                              time: formatDateTime(event.updated_at, translate("common.labels.recent")),
                            })}
                          </p>
                          <div className="flex flex-wrap items-center gap-2">
                            <Button size="sm" variant="ghost" onClick={() => void removeEvent(event)} disabled={busyEvent === "delete"}>
                              <Trash2 className="mr-1.5 h-4 w-4" />
                              {translate("common.actions.delete")}
                            </Button>
                            <Button size="sm" onClick={() => void submitEditedEvent()} disabled={busyEvent === "save"}>
                              {busyEvent === "save" ? `${translate("common.actions.save")}...` : translate("common.actions.save")}
                            </Button>
                          </div>
                        </div>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </Card>
          ) : null}
          </>
        )}
      </div>
    </div>
  );
}
