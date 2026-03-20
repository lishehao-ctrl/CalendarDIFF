"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Plus, Trash2 } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  createManualEvent,
  deleteManualEvent,
  listManualEvents,
  updateManualEvent,
} from "@/lib/api/manual";
import { listFamilies } from "@/lib/api/families";
import { useApiResource } from "@/lib/use-api-resource";
import { formatDateTime, formatSemanticDue } from "@/lib/presenters";
import type { CourseWorkItemFamily, ManualEvent } from "@/lib/types";

type Banner = {
  tone: "info" | "error";
  text: string;
} | null;

type ManualSection = "events" | "add";

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

function SectionButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        active
          ? "rounded-[0.95rem] bg-ink px-4 py-2 text-sm font-medium text-paper transition"
          : "rounded-[0.95rem] px-4 py-2 text-sm font-medium text-[#596270] transition hover:bg-white"
      }
    >
      {label}
    </button>
  );
}

export function ManualWorkbenchPanel() {
  const families = useApiResource<CourseWorkItemFamily[]>(() => listFamilies(), []);
  const manualEvents = useApiResource<ManualEvent[]>(() => listManualEvents(), []);

  const [banner, setBanner] = useState<Banner>(null);
  const [section, setSection] = useState<ManualSection>("events");
  const [selectedCourseKey, setSelectedCourseKey] = useState("");
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
        if (selectedCourseKey && event.course_display !== selectedCourseKey) return false;
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
    if (!selectedCourseKey) return familyRows;
    return familiesByCourse.get(selectedCourseKey) || [];
  }, [familiesByCourse, familyRows, selectedCourseKey]);
  const addFormFamilies = useMemo(() => {
    if (!addCourseKey) return familyRows;
    return familiesByCourse.get(addCourseKey) || [];
  }, [addCourseKey, familiesByCourse, familyRows]);
  const courseCount = familyCourseOptions.length;

  useEffect(() => {
    if (!familyRows.length) {
      setSelectedCourseKey((prev) => (courseOptions.includes(prev) ? prev : courseOptions[0] || ""));
      setAddCourseKey("");
      setSelectedFamilyId("all");
      setAddEventForm((prev) => ({ ...prev, familyId: "" }));
      return;
    }

    const nextCourseKey = courseOptions.includes(selectedCourseKey) ? selectedCourseKey : courseOptions[0];
    const nextAddCourseKey = familyCourseOptions.includes(addCourseKey) ? addCourseKey : familyCourseOptions[0];

    if (nextCourseKey && nextCourseKey !== selectedCourseKey) setSelectedCourseKey(nextCourseKey);
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
    setSelectedCourseKey(event.course_display);
    setSelectedFamilyId(event.family_id ? String(event.family_id) : "all");
    setBanner(null);
  }

  async function submitEditedEvent() {
    if (!expandedEventUid) return;
    const payload = normalizeEventForm(editEventForm);
    if (!payload) {
      setBanner({ tone: "error", text: "Family, event name, and due date are required." });
      return;
    }
    setBusyEvent("save");
    setBanner(null);
    try {
      await updateManualEvent(expandedEventUid, payload);
      setBanner({ tone: "info", text: "Event updated." });
      await manualEvents.refresh();
      clearExpandedEvent();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to save event" });
    } finally {
      setBusyEvent(null);
    }
  }

  async function submitNewEvent() {
    const payload = normalizeEventForm(addEventForm);
    if (!payload) {
      setBanner({ tone: "error", text: "Family, event name, and due date are required." });
      return;
    }
    setBusyEvent("create");
    setBanner(null);
    try {
      await createManualEvent(payload);
      setBanner({ tone: "info", text: "Event added." });
      await manualEvents.refresh();
      setSection("events");
      setSelectedCourseKey(addCourseKey);
      setSelectedFamilyId(String(payload.family_id));
      setAddEventForm((prev) => emptyEventForm(prev.familyId || String(payload.family_id)));
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to add event" });
    } finally {
      setBusyEvent(null);
    }
  }

  async function removeEvent(event: ManualEvent) {
    if (typeof window !== "undefined" && !window.confirm(`Delete ${eventSummaryLabel(event)}?`)) {
      return;
    }
    setBusyEvent("delete");
    setBanner(null);
    try {
      await deleteManualEvent(event.entity_uid, "manual cleanup");
      setBanner({ tone: "info", text: "Event deleted." });
      await manualEvents.refresh();
      if (expandedEventUid === event.entity_uid) {
        clearExpandedEvent();
      }
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to delete event" });
    } finally {
      setBusyEvent(null);
    }
  }

  if (families.loading || manualEvents.loading) return <LoadingState label="manual workspace" />;
  if (families.error) return <ErrorState message={families.error} />;
  if (manualEvents.error) return <ErrorState message={manualEvents.error} />;

  return (
    <div className="space-y-6">
      {banner ? (
        <Card className={banner.tone === "error" ? "border-[#e9b9ab] bg-[#fff3ef] p-4" : "bg-white/75 p-4"}>
          <p className={banner.tone === "error" ? "text-sm text-[#7f3d2a]" : "text-sm text-[#314051]"}>{banner.text}</p>
        </Card>
      ) : null}

      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="inline-flex flex-wrap items-center gap-1 rounded-[1rem] border border-line/80 bg-white/72 p-1 shadow-[var(--shadow-panel)]">
          <SectionButton active={section === "events"} label="Events" onClick={() => setSection("events")} />
          <SectionButton active={section === "add"} label="Add Event" onClick={() => setSection("add")} />
        </div>
        <p className="text-sm text-[#596270]">
          {eventRows.length} events · {courseCount} courses
        </p>
      </div>

      {section === "events" ? (
        <div className="space-y-4">
          <Card className="p-5">
            <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
              <div>
                <FieldLabel htmlFor="manual-events-course">Course</FieldLabel>
                <select
                  id="manual-events-course"
                  value={selectedCourseKey}
                  onChange={(event) => setSelectedCourseKey(event.target.value)}
                  className={selectClassName}
                >
                  {courseOptions.map((course) => (
                    <option key={course} value={course}>
                      {course}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <FieldLabel htmlFor="manual-events-family">Family</FieldLabel>
                <select
                  id="manual-events-family"
                  value={selectedFamilyId}
                  onChange={(event) => setSelectedFamilyId(event.target.value)}
                  className={selectClassName}
                >
                  <option value="all">All families</option>
                  {eventFilterFamilies.map((family) => (
                    <option key={family.id} value={family.id}>
                      {family.canonical_label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="pb-2 text-sm text-[#596270]">{filteredEventRows.length} events</div>
            </div>
          </Card>

          {filteredEventRows.length === 0 ? (
            <EmptyState title="No events in this view" description="Pick another course or family, or add a manual event from the Add Event block." />
          ) : (
            <Card className="p-4">
              <div className="space-y-3">
                {filteredEventRows.map((event) => {
                  const expanded = expandedEventUid === event.entity_uid;
                  return (
                    <div key={event.entity_uid} className="rounded-[1.15rem] border border-line/80 bg-white/78 px-4 py-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-ink">{eventSummaryLabel(event)}</p>
                        </div>
                        <Button size="sm" variant="ghost" onClick={() => (expanded ? clearExpandedEvent() : openEvent(event))}>
                          {expanded ? "Close" : "Open"}
                          {expanded ? <ChevronUp className="ml-2 h-4 w-4" /> : <ChevronDown className="ml-2 h-4 w-4" />}
                        </Button>
                      </div>

                      {expanded ? (
                        <div className="mt-4 border-t border-line/70 pt-4">
                          <div className="grid gap-4 md:grid-cols-2">
                            <div>
                              <FieldLabel htmlFor={`event-family-${event.entity_uid}`}>Family</FieldLabel>
                              <select
                                id={`event-family-${event.entity_uid}`}
                                value={editEventForm.familyId}
                                onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, familyId: nextEvent.target.value }))}
                                className={selectClassName}
                              >
                                <option value="">Select a family</option>
                                {familyRows.map((family) => (
                                  <option key={family.id} value={family.id}>
                                    {family.course_display} - {family.canonical_label}
                                  </option>
                                ))}
                              </select>
                            </div>
                            <div>
                              <FieldLabel htmlFor={`event-name-${event.entity_uid}`}>Event name</FieldLabel>
                              <Input
                                id={`event-name-${event.entity_uid}`}
                                value={editEventForm.eventName}
                                onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, eventName: nextEvent.target.value }))}
                              />
                            </div>
                            <div>
                              <FieldLabel htmlFor={`event-raw-type-${event.entity_uid}`}>Raw type</FieldLabel>
                              <Input
                                id={`event-raw-type-${event.entity_uid}`}
                                value={editEventForm.rawType}
                                onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, rawType: nextEvent.target.value }))}
                              />
                            </div>
                            <div>
                              <FieldLabel htmlFor={`event-ordinal-${event.entity_uid}`}>Number</FieldLabel>
                              <Input
                                id={`event-ordinal-${event.entity_uid}`}
                                value={editEventForm.ordinal}
                                onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, ordinal: nextEvent.target.value }))}
                                placeholder="3"
                              />
                            </div>
                            <div>
                              <FieldLabel htmlFor={`event-date-${event.entity_uid}`}>Due date</FieldLabel>
                              <Input
                                id={`event-date-${event.entity_uid}`}
                                type="date"
                                value={editEventForm.dueDate}
                                onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, dueDate: nextEvent.target.value }))}
                              />
                            </div>
                            <div>
                              <FieldLabel htmlFor={`event-precision-${event.entity_uid}`}>Time mode</FieldLabel>
                              <select
                                id={`event-precision-${event.entity_uid}`}
                                value={editEventForm.timePrecision}
                                onChange={(nextEvent) =>
                                  setEditEventForm((prev) => ({ ...prev, timePrecision: nextEvent.target.value as "date_only" | "datetime" }))
                                }
                                className={selectClassName}
                              >
                                <option value="date_only">Date only</option>
                                <option value="datetime">Date and time</option>
                              </select>
                            </div>
                            {editEventForm.timePrecision === "datetime" ? (
                              <div>
                                <FieldLabel htmlFor={`event-time-${event.entity_uid}`}>Due time</FieldLabel>
                                <Input
                                  id={`event-time-${event.entity_uid}`}
                                  type="time"
                                  value={editEventForm.dueTime}
                                  onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, dueTime: nextEvent.target.value }))}
                                />
                              </div>
                            ) : null}
                          </div>
                          <div className="mt-4">
                            <FieldLabel htmlFor={`event-reason-${event.entity_uid}`}>Reason</FieldLabel>
                            <Textarea
                              id={`event-reason-${event.entity_uid}`}
                              value={editEventForm.reason}
                              onChange={(nextEvent) => setEditEventForm((prev) => ({ ...prev, reason: nextEvent.target.value }))}
                              placeholder="Optional note for the audit trail"
                              className="min-h-[92px]"
                            />
                          </div>
                          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                            <p className="text-sm text-[#596270]">
                              {formatSemanticDue(event as unknown as Record<string, unknown>, "No due date")} · Updated {formatDateTime(event.updated_at, "Recently")}
                            </p>
                            <div className="flex flex-wrap items-center gap-2">
                              <Button size="sm" variant="ghost" onClick={() => void removeEvent(event)} disabled={busyEvent === "delete"}>
                                <Trash2 className="mr-1.5 h-4 w-4" />
                                Delete
                              </Button>
                              <Button size="sm" onClick={() => void submitEditedEvent()} disabled={busyEvent === "save"}>
                                {busyEvent === "save" ? "Saving..." : "Save"}
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
          )}
        </div>
      ) : null}

      {section === "add" ? (
        <div className="space-y-4">
          {!familyRows.length ? (
            <EmptyState title="No families yet" description="Create a family from Family before adding manual events under it." />
          ) : (
            <>
              <Card className="p-5">
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <FieldLabel htmlFor="manual-add-course">Course</FieldLabel>
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
                    <FieldLabel htmlFor="manual-add-family">Family</FieldLabel>
                    <select
                      id="manual-add-family"
                      value={addEventForm.familyId}
                      onChange={(event) => setAddEventForm((prev) => ({ ...prev, familyId: event.target.value }))}
                      className={selectClassName}
                    >
                      <option value="">Select a family</option>
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
                    <FieldLabel htmlFor="manual-add-name">Event name</FieldLabel>
                    <Input id="manual-add-name" value={addEventForm.eventName} onChange={(event) => setAddEventForm((prev) => ({ ...prev, eventName: event.target.value }))} placeholder="Homework 5" />
                  </div>
                  <div>
                    <FieldLabel htmlFor="manual-add-raw-type">Raw type</FieldLabel>
                    <Input id="manual-add-raw-type" value={addEventForm.rawType} onChange={(event) => setAddEventForm((prev) => ({ ...prev, rawType: event.target.value }))} placeholder="hw" />
                  </div>
                  <div>
                    <FieldLabel htmlFor="manual-add-ordinal">Number</FieldLabel>
                    <Input id="manual-add-ordinal" value={addEventForm.ordinal} onChange={(event) => setAddEventForm((prev) => ({ ...prev, ordinal: event.target.value }))} placeholder="5" />
                  </div>
                  <div>
                    <FieldLabel htmlFor="manual-add-date">Due date</FieldLabel>
                    <Input id="manual-add-date" type="date" value={addEventForm.dueDate} onChange={(event) => setAddEventForm((prev) => ({ ...prev, dueDate: event.target.value }))} />
                  </div>
                  <div>
                    <FieldLabel htmlFor="manual-add-precision">Time mode</FieldLabel>
                    <select
                      id="manual-add-precision"
                      value={addEventForm.timePrecision}
                      onChange={(event) => setAddEventForm((prev) => ({ ...prev, timePrecision: event.target.value as "date_only" | "datetime" }))}
                      className={selectClassName}
                    >
                      <option value="date_only">Date only</option>
                      <option value="datetime">Date and time</option>
                    </select>
                  </div>
                  {addEventForm.timePrecision === "datetime" ? (
                    <div>
                      <FieldLabel htmlFor="manual-add-time">Due time</FieldLabel>
                      <Input id="manual-add-time" type="time" value={addEventForm.dueTime} onChange={(event) => setAddEventForm((prev) => ({ ...prev, dueTime: event.target.value }))} />
                    </div>
                  ) : null}
                </div>
                <div className="mt-4">
                  <FieldLabel htmlFor="manual-add-reason">Reason</FieldLabel>
                  <Textarea id="manual-add-reason" value={addEventForm.reason} onChange={(event) => setAddEventForm((prev) => ({ ...prev, reason: event.target.value }))} placeholder="Optional note for the audit trail" className="min-h-[92px]" />
                </div>
                <div className="mt-4 flex justify-end">
                  <Button onClick={() => void submitNewEvent()} disabled={busyEvent === "create" || !addFormFamilies.length}>
                    <Plus className="mr-2 h-4 w-4" />
                    {busyEvent === "create" ? "Adding..." : "Add event"}
                  </Button>
                </div>
              </Card>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
