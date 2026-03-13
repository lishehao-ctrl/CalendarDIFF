"use client";

import { useEffect, useMemo, useState } from "react";
import { Clock3, Mail, Plus, Tags, Trash2, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import {
  createCourseWorkItemFamily,
  deleteCourseWorkItemFamily,
  getCourseWorkItemFamilyStatus,
  getCurrentUser,
  listCourseWorkItemFamilies,
  listKnownCourseKeys,
  updateCourseWorkItemFamily,
  updateCurrentUser,
} from "@/lib/api/users";
import { getBrowserTimeZone } from "@/lib/browser-timezone";
import { useApiResource } from "@/lib/use-api-resource";
import { formatCourseDisplay, formatDateTime } from "@/lib/presenters";
import type { CourseIdentity, CourseWorkItemFamily, CourseWorkItemFamilyStatus, UserProfile } from "@/lib/types";

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

export function SettingsPanel() {
  const user = useApiResource<UserProfile>(() => getCurrentUser(), []);
  const families = useApiResource<CourseWorkItemFamily[]>(() => listCourseWorkItemFamilies(), []);
  const status = useApiResource<CourseWorkItemFamilyStatus>(() => getCourseWorkItemFamilyStatus(), []);
  const courses = useApiResource<{ courses: CourseIdentity[] }>(() => listKnownCourseKeys(), []);

  const [form, setForm] = useState({ timezone_name: "" });
  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [savingUser, setSavingUser] = useState(false);
  const [busyFamily, setBusyFamily] = useState<number | "new" | null>(null);
  const [newCourseIdentity, setNewCourseIdentity] = useState(emptyCourseIdentity());
  const [newCanonicalLabel, setNewCanonicalLabel] = useState("");
  const [draftCourseIdentities, setDraftCourseIdentities] = useState<Record<number, ReturnType<typeof emptyCourseIdentity>>>({});
  const [draftLabels, setDraftLabels] = useState<Record<number, string>>({});
  const [draftRawTypes, setDraftRawTypes] = useState<Record<number, string[]>>({});
  const [rawTypeInputs, setRawTypeInputs] = useState<Record<number, string>>({});
  const [deviceTimeZone, setDeviceTimeZone] = useState<string | null>(null);

  useEffect(() => {
    setDeviceTimeZone(getBrowserTimeZone());
  }, []);

  useEffect(() => {
    if (user.data) setForm({ timezone_name: user.data.timezone_name || "" });
  }, [user.data]);

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

  const familyRows = useMemo(() => families.data || [], [families.data]);
  const groupedFamilies = useMemo(() => {
    const groups = new Map<string, CourseWorkItemFamily[]>();
    for (const family of familyRows) {
      if (!groups.has(family.course_display)) groups.set(family.course_display, []);
      groups.get(family.course_display)!.push(family);
    }
    return Array.from(groups.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [familyRows]);

  async function refreshFamilies() {
    await Promise.all([families.refresh(), status.refresh(), courses.refresh()]);
  }

  async function saveUser() {
    setSavingUser(true);
    setBanner(null);
    try {
      await updateCurrentUser({ timezone_name: form.timezone_name, timezone_source: "manual" });
      setBanner({ tone: "info", text: "Settings saved." });
      await user.refresh();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to save settings" });
    } finally {
      setSavingUser(false);
    }
  }

  function applyDeviceTimeZone() {
    if (!deviceTimeZone) return;
    setForm({ timezone_name: deviceTimeZone });
    setBanner(null);
  }

  async function createFamily() {
    const canonicalLabel = newCanonicalLabel.trim();
    const identity = normalizeCourseIdentityForm(newCourseIdentity);
    if (!identity || !canonicalLabel) return;
    setBusyFamily("new");
    setBanner(null);
    try {
      await createCourseWorkItemFamily({ ...identity, canonical_label: canonicalLabel, raw_types: [] });
      setNewCourseIdentity(emptyCourseIdentity());
      setNewCanonicalLabel("");
      setBanner({ tone: "info", text: `Created “${canonicalLabel}”.` });
      await refreshFamilies();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to create family" });
    } finally {
      setBusyFamily(null);
    }
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
      setBanner({ tone: "info", text: `Updated “${canonicalLabel}”.` });
      await refreshFamilies();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to update family" });
    } finally {
      setBusyFamily(null);
    }
  }

  async function removeFamily(familyId: number) {
    const confirmed = window.confirm("Delete this course family and all of its raw types?");
    if (!confirmed) return;
    setBusyFamily(familyId);
    setBanner(null);
    try {
      await deleteCourseWorkItemFamily(familyId);
      setBanner({ tone: "info", text: "Family deleted." });
      await refreshFamilies();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to delete family" });
    } finally {
      setBusyFamily(null);
    }
  }

  function addRawType(familyId: number) {
    const rawType = (rawTypeInputs[familyId] || "").trim();
    if (!rawType) return;
    setDraftRawTypes((prev) => ({ ...prev, [familyId]: [...(prev[familyId] || []), rawType] }));
    setRawTypeInputs((prev) => ({ ...prev, [familyId]: "" }));
  }

  function removeRawType(familyId: number, rawType: string) {
    setDraftRawTypes((prev) => ({ ...prev, [familyId]: (prev[familyId] || []).filter((row) => row !== rawType) }));
  }

  if (user.loading || families.loading || status.loading || courses.loading) return <LoadingState label="settings" />;
  if (user.error) return <ErrorState message={user.error} />;
  if (families.error) return <ErrorState message={families.error} />;
  if (status.error) return <ErrorState message={status.error} />;
  if (courses.error) return <ErrorState message={courses.error} />;
  if (!user.data) return <EmptyState title="User not initialized" description="Complete registration before editing settings." />;

  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_0.9fr]">
      <div className="space-y-5">
        <Card className="p-6 md:p-7">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Editable settings</p>
          <h3 className="mt-3 text-2xl font-semibold">Workspace identity</h3>
          <p className="mt-2 text-sm leading-6 text-[#596270]">Login email is managed by auth. This page edits stable runtime preferences and course label families.</p>
          {banner ? <div className={banner.tone === 'error' ? 'mt-5 rounded-[1.15rem] border border-[#efc4b5] bg-[#fff3ef] px-4 py-3 text-sm text-[#7f3d2a]' : 'mt-5 rounded-[1.15rem] border border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] px-4 py-3 text-sm text-[#314051]'}>{banner.text}</div> : null}
          <div className="mt-6 space-y-4">
            <div>
              <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="notify-email-settings">Login / notify email</label>
              <Input id="notify-email-settings" value={user.data.notify_email || ''} disabled />
            </div>
            <div>
              <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="timezone-name">Timezone name</label>
              <Input id="timezone-name" value={form.timezone_name} onChange={(event) => setForm({ timezone_name: event.target.value })} placeholder="America/Los_Angeles" />
              <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-[#596270]">
                <span>Detected device timezone: {deviceTimeZone || "Unavailable"}</span>
                {deviceTimeZone ? (
                  <button type="button" className="font-medium text-cobalt transition hover:text-[#1f4fd6]" onClick={applyDeviceTimeZone}>
                    Use device timezone
                  </button>
                ) : null}
              </div>
            </div>
            <Button onClick={() => void saveUser()} disabled={savingUser || !form.timezone_name}>{savingUser ? 'Saving settings...' : 'Save settings'}</Button>
          </div>
        </Card>

        <Card className="p-6 md:p-7">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Course label families</p>
              <h3 className="mt-3 text-2xl font-semibold">Canonical label families</h3>
              <p className="mt-2 text-sm leading-6 text-[#596270]">Review is the primary learning workflow. Settings is the advanced place to manage a course’s canonical labels and raw type membership.</p>
            </div>
            <div className="rounded-[1.15rem] border border-line/80 bg-white/70 px-4 py-3 text-sm text-[#314051]">
              <p className="font-medium text-ink">Rebuild status</p>
              <p className="mt-1">State: {status.data?.state || 'idle'}</p>
              <p className="mt-1">Last rebuilt: {formatDateTime(status.data?.last_rebuilt_at, 'Never')}</p>
              {status.data?.last_error ? <p className="mt-1 text-[#7f3d2a]">{status.data.last_error}</p> : null}
            </div>
          </div>

          <div className="mt-6 rounded-[1.15rem] border border-line/80 bg-white/70 p-4">
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Create family</p>
            <div className="mt-3 grid gap-3 md:grid-cols-[1fr_1fr_1fr]">
              <Input value={newCourseIdentity.course_dept} onChange={(event) => setNewCourseIdentity((prev) => ({ ...prev, course_dept: event.target.value }))} placeholder="CSE" />
              <Input value={newCourseIdentity.course_number} onChange={(event) => setNewCourseIdentity((prev) => ({ ...prev, course_number: event.target.value }))} placeholder="100" />
              <Input value={newCourseIdentity.course_suffix} onChange={(event) => setNewCourseIdentity((prev) => ({ ...prev, course_suffix: event.target.value }))} placeholder="A" />
              <Input value={newCourseIdentity.course_quarter} onChange={(event) => setNewCourseIdentity((prev) => ({ ...prev, course_quarter: event.target.value }))} placeholder="WI" />
              <Input value={newCourseIdentity.course_year2} onChange={(event) => setNewCourseIdentity((prev) => ({ ...prev, course_year2: event.target.value }))} placeholder="26" />
              <Input id="new-course-family-label" value={newCanonicalLabel} onChange={(event) => setNewCanonicalLabel(event.target.value)} placeholder="Homework" />
              <Button onClick={() => void createFamily()} disabled={busyFamily === 'new' || !normalizeCourseIdentityForm(newCourseIdentity) || !newCanonicalLabel.trim()}>
                <Plus className="mr-2 h-4 w-4" />
                {busyFamily === 'new' ? 'Creating...' : 'Add family'}
              </Button>
            </div>
            {courses.data?.courses?.length ? <p className="mt-3 text-xs text-[#596270]">Known courses: {courses.data.courses.map((course: CourseIdentity) => course.course_display).join(', ')}</p> : null}
          </div>

          <div className="mt-5 space-y-5">
            {groupedFamilies.length === 0 ? (
              <EmptyState title="No course families yet" description="Families will be learned through Review, or you can create them here manually." />
            ) : groupedFamilies.map(([courseKey, rows]) => (
              <div key={courseKey} className="space-y-3">
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{courseKey}</p>
                {rows.map((family) => (
                  <Card key={family.id} className="bg-white/60 p-5">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div className="min-w-0 flex-1 space-y-4">
                        <div className="grid gap-3 md:grid-cols-2">
                          <div>
                            <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]">Course display</label>
                            <Input value={formatCourseDisplay(family as unknown as Record<string, unknown>)} disabled />
                          </div>
                          <div>
                            <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]">Canonical label</label>
                            <Input value={draftLabels[family.id] || ''} onChange={(event) => setDraftLabels((prev) => ({ ...prev, [family.id]: event.target.value }))} placeholder="Homework" />
                          </div>
                        </div>
                        <div className="grid gap-3 md:grid-cols-5">
                          <Input value={draftCourseIdentities[family.id]?.course_dept || ''} onChange={(event) => setDraftCourseIdentities((prev) => ({ ...prev, [family.id]: { ...(prev[family.id] || emptyCourseIdentity()), course_dept: event.target.value } }))} placeholder="Dept" />
                          <Input value={draftCourseIdentities[family.id]?.course_number || ''} onChange={(event) => setDraftCourseIdentities((prev) => ({ ...prev, [family.id]: { ...(prev[family.id] || emptyCourseIdentity()), course_number: event.target.value } }))} placeholder="Number" />
                          <Input value={draftCourseIdentities[family.id]?.course_suffix || ''} onChange={(event) => setDraftCourseIdentities((prev) => ({ ...prev, [family.id]: { ...(prev[family.id] || emptyCourseIdentity()), course_suffix: event.target.value } }))} placeholder="Suffix" />
                          <Input value={draftCourseIdentities[family.id]?.course_quarter || ''} onChange={(event) => setDraftCourseIdentities((prev) => ({ ...prev, [family.id]: { ...(prev[family.id] || emptyCourseIdentity()), course_quarter: event.target.value } }))} placeholder="Quarter" />
                          <Input value={draftCourseIdentities[family.id]?.course_year2 || ''} onChange={(event) => setDraftCourseIdentities((prev) => ({ ...prev, [family.id]: { ...(prev[family.id] || emptyCourseIdentity()), course_year2: event.target.value } }))} placeholder="Year2" />
                        </div>
                        <div>
                          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Raw Types</p>
                          <div className="mt-3 flex flex-wrap gap-2">
                            {(draftRawTypes[family.id] || []).map((rawType) => (
                              <span key={`${family.id}-${rawType}`} className="inline-flex items-center gap-2 rounded-full border border-line/80 bg-white/80 px-3 py-1 text-sm text-[#314051]">
                                {rawType}
                                <button type="button" aria-label={`Remove raw type ${rawType}`} onClick={() => removeRawType(family.id, rawType)}>
                                  <X className="h-3.5 w-3.5" />
                                </button>
                              </span>
                            ))}
                          </div>
                          <div className="mt-3 flex flex-wrap gap-3">
                            <Input value={rawTypeInputs[family.id] || ''} onChange={(event) => setRawTypeInputs((prev) => ({ ...prev, [family.id]: event.target.value }))} placeholder="hw" className="max-w-sm" />
                            <Button variant="ghost" onClick={() => addRawType(family.id)} disabled={!(rawTypeInputs[family.id] || '').trim()}>
                              <Plus className="mr-2 h-4 w-4" />
                              Add raw type
                            </Button>
                          </div>
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button onClick={() => void saveFamily(family.id)} disabled={busyFamily === family.id}>{busyFamily === family.id ? 'Saving...' : 'Save'}</Button>
                        <Button variant="ghost" onClick={() => void removeFamily(family.id)} disabled={busyFamily === family.id}><Trash2 className="mr-2 h-4 w-4" />Delete</Button>
                      </div>
                    </div>
                  </Card>
                ))}
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div className="space-y-5">
        <Card className="p-6">
          <div className="flex items-center gap-3"><div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(31,94,255,0.1)] text-cobalt"><Mail className="h-5 w-5" /></div><div><p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Identity snapshot</p><h3 className="mt-1 text-xl font-semibold">Current profile</h3></div></div>
          <div className="mt-5 space-y-3 text-sm text-[#314051]">
            <div className="rounded-[1.15rem] border border-line/80 bg-white/60 p-4"><p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Login / notify email</p><p className="mt-2 font-medium">{user.data.notify_email || 'Not set'}</p><p className="mt-2 text-xs text-[#596270]">This identifier is managed by auth and intentionally stays read-only inside the app.</p></div>
            <div className="rounded-[1.15rem] border border-line/80 bg-white/60 p-4"><p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Created</p><p className="mt-2 font-medium">{formatDateTime(user.data.created_at, 'Not available')}</p></div>
          </div>
        </Card>
        <Card className="p-6">
          <div className="flex items-center gap-3"><div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(47,143,91,0.12)] text-moss"><Clock3 className="h-5 w-5" /></div><div><p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Timing defaults</p><h3 className="mt-1 text-xl font-semibold">Operational timing</h3></div></div>
          <div className="mt-5 rounded-[1.15rem] border border-line/80 bg-white/60 p-4 text-sm text-[#314051]"><p>Timezone: {user.data.timezone_name}</p><p className="mt-2">Timezone mode: {user.data.timezone_source === "manual" ? "Manual override" : "Auto from device region"}</p><p className="mt-2">Calendar delay seconds: {user.data.calendar_delay_seconds}</p></div>
          <div className="mt-4 rounded-[1.15rem] border border-line/80 bg-white/60 p-4 text-sm text-[#596270]">Review is the primary place where the system learns new course labels. Settings is for manual cleanup and overrides.</div>
        </Card>
        <Card className="p-6">
          <div className="flex items-center gap-3"><div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(20,32,44,0.08)] text-ink"><Tags className="h-5 w-5" /></div><div><p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Family summary</p><h3 className="mt-1 text-xl font-semibold">Current course memory</h3></div></div>
          <div className="mt-5 rounded-[1.15rem] border border-line/80 bg-white/60 p-4 text-sm text-[#314051]"><p>Known courses: {courses.data?.courses?.length || 0}</p><p className="mt-2">Families: {familyRows.length}</p><p className="mt-2">Raw types: {familyRows.reduce((count, row) => count + row.raw_types.length, 0)}</p><p className="mt-2">Last rebuild: {formatDateTime(status.data?.last_rebuilt_at, 'Never')}</p></div>
        </Card>
      </div>
    </div>
  );
}
