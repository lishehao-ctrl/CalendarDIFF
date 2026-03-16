"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Plus, Tags } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { createCourseWorkItemFamily, listCourseWorkItemFamilies, listKnownCourseKeys } from "@/lib/api/users";
import { useApiResource } from "@/lib/use-api-resource";
import type { CourseIdentity, CourseWorkItemFamily } from "@/lib/types";

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

function parseMatchingKeywords(input: string) {
  const seen = new Set<string>();
  return input
    .split(/[\n,;，]+/)
    .map((value) => value.trim())
    .filter((value) => value.length > 0)
    .filter((value) => {
      const normalized = value.toLowerCase();
      if (seen.has(normalized)) {
        return false;
      }
      seen.add(normalized);
      return true;
    });
}

export function AddFamilyPanel() {
  const families = useApiResource<CourseWorkItemFamily[]>(() => listCourseWorkItemFamilies(), []);
  const courses = useApiResource<{ courses: CourseIdentity[] }>(() => listKnownCourseKeys(), []);

  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [busyFamily, setBusyFamily] = useState(false);
  const [newCourseIdentity, setNewCourseIdentity] = useState(emptyCourseIdentity());
  const [newCanonicalLabel, setNewCanonicalLabel] = useState("");
  const [matchingKeywords, setMatchingKeywords] = useState("");

  const familyCount = useMemo(() => families.data?.length || 0, [families.data]);
  const parsedKeywords = useMemo(() => parseMatchingKeywords(matchingKeywords), [matchingKeywords]);

  async function createFamily() {
    const canonicalLabel = newCanonicalLabel.trim();
    const identity = normalizeCourseIdentityForm(newCourseIdentity);
    if (!identity || !canonicalLabel) return;
    setBusyFamily(true);
    setBanner(null);
    try {
      await createCourseWorkItemFamily({ ...identity, canonical_label: canonicalLabel, raw_types: parsedKeywords });
      setNewCourseIdentity(emptyCourseIdentity());
      setNewCanonicalLabel("");
      setMatchingKeywords("");
      setBanner({ tone: "info", text: `Created "${canonicalLabel}".` });
      await Promise.all([families.refresh(), courses.refresh()]);
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to create family" });
    } finally {
      setBusyFamily(false);
    }
  }

  if (families.loading || courses.loading) return <LoadingState label="add family" />;
  if (families.error) return <ErrorState message={families.error} />;
  if (courses.error) return <ErrorState message={courses.error} />;

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-[1.2rem] border border-line/80 bg-white/72 px-4 py-3 shadow-[var(--shadow-panel)] md:flex-row md:items-center md:justify-between">
        <div className="flex flex-wrap items-center gap-2 text-sm text-[#596270]">
          <span className="rounded-full bg-[rgba(20,32,44,0.06)] px-3 py-1.5 text-ink">{courses.data?.courses?.length || 0} courses</span>
          <span className="rounded-full bg-[rgba(20,32,44,0.06)] px-3 py-1.5 text-ink">{familyCount} families</span>
        </div>
        <Link href="/review/links" className="text-sm font-medium text-cobalt">
          Back to manage
        </Link>
      </div>

      {banner ? (
        <Card className={banner.tone === "error" ? "border-[#efc4b5] bg-[#fff3ef] p-4" : "border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] p-4"}>
          <p className="text-sm text-[#314051]">{banner.text}</p>
        </Card>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="bg-white/72 p-4">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(20,32,44,0.08)] text-ink">
              <Tags className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Create family</p>
              <h3 className="mt-1 text-lg font-semibold text-ink">Add family</h3>
            </div>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            <Input value={newCourseIdentity.course_dept} onChange={(event) => setNewCourseIdentity((prev) => ({ ...prev, course_dept: event.target.value }))} placeholder="CSE" />
            <Input value={newCourseIdentity.course_number} onChange={(event) => setNewCourseIdentity((prev) => ({ ...prev, course_number: event.target.value }))} placeholder="100" />
            <Input value={newCourseIdentity.course_suffix} onChange={(event) => setNewCourseIdentity((prev) => ({ ...prev, course_suffix: event.target.value }))} placeholder="A" />
            <Input value={newCourseIdentity.course_quarter} onChange={(event) => setNewCourseIdentity((prev) => ({ ...prev, course_quarter: event.target.value }))} placeholder="WI" />
            <Input value={newCourseIdentity.course_year2} onChange={(event) => setNewCourseIdentity((prev) => ({ ...prev, course_year2: event.target.value }))} placeholder="26" />
            <Input id="new-course-family-label" value={newCanonicalLabel} onChange={(event) => setNewCanonicalLabel(event.target.value)} placeholder="Homework" />
          </div>
          <div className="mt-4">
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Keywords for matching</p>
            <p className="mt-2 text-sm text-[#596270]">Comma or newline separated keywords will be saved as raw-type matches.</p>
            <Textarea
              className="mt-3 min-h-[110px]"
              value={matchingKeywords}
              onChange={(event) => setMatchingKeywords(event.target.value)}
              placeholder={"hw\nhomework\nreflection"}
            />
            {parsedKeywords.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {parsedKeywords.map((keyword) => (
                  <Badge key={keyword} tone="info">
                    {keyword}
                  </Badge>
                ))}
              </div>
            ) : null}
          </div>
          <div className="mt-4">
            <Button onClick={() => void createFamily()} disabled={busyFamily || !normalizeCourseIdentityForm(newCourseIdentity) || !newCanonicalLabel.trim()}>
              <Plus className="mr-2 h-4 w-4" />
              {busyFamily ? "Creating..." : "Add family"}
            </Button>
          </div>
        </Card>

        <div className="space-y-4">
          <Card className="bg-white/60 p-4">
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Known course memory</p>
            <p className="mt-2 text-sm text-[#596270]">Live course keys already seen in this workspace.</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {(courses.data?.courses || []).slice(0, 8).map((course: CourseIdentity) => (
                <Badge key={course.course_display} tone="info">
                  {course.course_display}
                </Badge>
              ))}
            </div>
            {(courses.data?.courses?.length || 0) > 8 ? (
              <p className="mt-3 text-xs text-[#596270]">Plus {courses.data!.courses.length - 8} more known course keys.</p>
            ) : null}
          </Card>

          {(courses.data?.courses?.length || 0) === 0 ? (
            <EmptyState title="No known courses yet" description="You can still add a family manually with a new course identity." />
          ) : null}
        </div>
      </div>
    </div>
  );
}
