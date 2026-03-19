"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Eye, Save } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { applyReviewEdit, getReviewChangeEditContext, previewReviewEdit } from "@/lib/api/review";
import { withBasePath } from "@/lib/demo-mode";
import { formatCourseDisplay, formatSemanticDue, formatStatusLabel } from "@/lib/presenters";
import type { ReviewEditContext, ReviewEditMode, ReviewEditPreviewResponse, ReviewEditRequest } from "@/lib/types";
import { useApiResource } from "@/lib/use-api-resource";
import { useRouter } from "next/navigation";

function ReviewEditEventCard({
  title,
  event,
}: {
  title: string;
  event: ReviewEditPreviewResponse["base"];
}) {
  return (
    <div className="rounded-[1.2rem] border border-line/80 bg-white/70 p-4 text-sm text-[#314051]">
      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{title}</p>
      <p className="mt-2 font-medium text-ink">{event.event_display.display_label}</p>
      <p className="mt-1 text-xs text-[#6d7885]">{event.event_display.course_display}</p>
      <div className="mt-4 space-y-1.5">
        <p>Family: {event.event_display.family_name}</p>
        <p>Ordinal: {event.event_display.ordinal ?? "N/A"}</p>
        <p>Due: {formatSemanticDue(event as unknown as Record<string, unknown>, "N/A")}</p>
      </div>
    </div>
  );
}

export function ReviewChangeEditPageClient({ mode, changeId, basePath = "" }: { mode: ReviewEditMode; changeId: number; basePath?: string }) {
  const router = useRouter();
  const { data, loading, error } = useApiResource<ReviewEditContext>(() => getReviewChangeEditContext(changeId), [changeId]);
  const [form, setForm] = useState({
    due_date: "",
    due_time: "",
    time_precision: "datetime" as "date_only" | "datetime",
    event_name: "",
    course_dept: "",
    course_number: "",
    course_suffix: "",
    course_quarter: "",
    course_year2: "",
    reason: ""
  });
  const [preview, setPreview] = useState<ReviewEditPreviewResponse | null>(null);
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);

  useEffect(() => {
    if (!data) {
      return;
    }
    const editable = data.editable_event;
    setForm({
      due_date: typeof editable.due_date === "string" ? editable.due_date : "",
      due_time: typeof editable.due_time === "string" ? editable.due_time : "",
      time_precision: editable.time_precision === "date_only" ? "date_only" : "datetime",
      event_name: typeof editable.event_name === "string" ? editable.event_name : "",
      course_dept: typeof editable.course_dept === "string" ? editable.course_dept : "",
      course_number: typeof editable.course_number === "number" ? String(editable.course_number) : "",
      course_suffix: typeof editable.course_suffix === "string" ? editable.course_suffix : "",
      course_quarter: typeof editable.course_quarter === "string" ? editable.course_quarter : "",
      course_year2: typeof editable.course_year2 === "number" ? String(editable.course_year2).padStart(2, "0") : "",
      reason: ""
    });
  }, [data]);

  const pageTitle = useMemo(() => {
    return data?.editable_event.family_name || data?.entity_uid || "Review change";
  }, [data]);

  function buildEditRequest(): ReviewEditRequest | null {
    if (!data) {
      return null;
    }

    return {
      mode,
      target: { change_id: data.change_id },
      patch: {
        due_date: form.due_date || null,
        due_time: form.time_precision === "date_only" ? null : form.due_time || null,
        time_precision: form.time_precision,
        event_name: form.event_name || null,
        course_dept: form.course_dept || null,
        course_number: form.course_number ? Number(form.course_number) : null,
        course_suffix: form.course_suffix || null,
        course_quarter: form.course_quarter ? (form.course_quarter as "WI" | "SP" | "SU" | "FA") : null,
        course_year2: form.course_year2 ? Number(form.course_year2) : null
      },
      reason: form.reason || null
    };
  }

  async function runPreview() {
    const request = buildEditRequest();
    if (!request) {
      return;
    }
    setBusy("preview");
    setBanner(null);
    try {
      const payload = await previewReviewEdit(request);
      setPreview(payload);
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Preview failed" });
    } finally {
      setBusy(null);
    }
  }

  async function applyEdit() {
    const request = buildEditRequest();
    if (!request) {
      return;
    }
    setBusy("apply");
    setBanner(null);
    try {
      const payload = await applyReviewEdit(request);
      setBanner({
        tone: "info",
        text: payload.mode === "proposal" ? "Proposal updated. Returning to review inbox..." : "Current event updated. Returning to review inbox..."
      });
      setTimeout(() => {
        router.push(withBasePath(basePath, "/review/changes"));
        router.refresh();
      }, 300);
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Apply failed" });
    } finally {
      setBusy(null);
    }
  }

  if (loading) {
    return <LoadingState label={mode === "proposal" ? "proposal edit" : "direct edit"} />;
  }
  if (error) {
    return <ErrorState message={error} />;
  }
  if (!data) {
    return <EmptyState title="Change not found" description="This review change is unavailable or you do not have access to it." />;
  }

  return (
    <div className="space-y-5">
      <Card className="p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Edit workspace</p>
            <h3 className="mt-3 text-2xl font-semibold text-ink">{pageTitle}</h3>
            <p className="mt-2 text-sm leading-6 text-[#596270]">
              {mode === "proposal"
                ? "Adjust the pending proposal before it is approved."
                : "Apply a direct correction to the current approved event."}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="info">{formatStatusLabel(mode)}</Badge>
            <Button asChild size="sm" variant="ghost">
              <Link href={withBasePath(basePath, "/review/changes")}>
                <ArrowLeft className="mr-2 h-4 w-4" />
                Back to inbox
              </Link>
            </Button>
          </div>
        </div>

        {banner ? (
          <div className={banner.tone === "error" ? "mt-5 rounded-[1.15rem] border border-[#efc4b5] bg-[#fff3ef] px-4 py-3 text-sm text-[#7f3d2a]" : "mt-5 rounded-[1.15rem] border border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] px-4 py-3 text-sm text-[#314051]"}>
            {banner.text}
          </div>
        ) : null}

        <div className="mt-6 grid gap-5 xl:grid-cols-[1fr_0.95fr]">
          <Card className="bg-white/60 p-5">
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Edit fields</p>
            <div className="mt-4 space-y-4">
              <div>
                <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="review-edit-due-at">
                  Due date
                </label>
                <Input id="review-edit-due-at" type="date" value={form.due_date} onChange={(event) => setForm((prev) => ({ ...prev, due_date: event.target.value }))} />
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div>
                  <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="review-edit-due-time">
                    Due time
                  </label>
                  <Input id="review-edit-due-time" type="time" value={form.due_time} disabled={form.time_precision === "date_only"} onChange={(event) => setForm((prev) => ({ ...prev, due_time: event.target.value }))} />
                </div>
                <div>
                  <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="review-edit-time-precision">
                    Time precision
                  </label>
                  <select id="review-edit-time-precision" value={form.time_precision} onChange={(event) => setForm((prev) => ({ ...prev, time_precision: event.target.value as "date_only" | "datetime" }))} className="flex h-10 w-full rounded-xl border border-input bg-background px-3 py-2 text-sm">
                    <option value="datetime">Datetime</option>
                    <option value="date_only">Date only</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="review-edit-event-name">
                  Event name
                </label>
                <Input id="review-edit-event-name" value={form.event_name} onChange={(event) => setForm((prev) => ({ ...prev, event_name: event.target.value }))} />
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div>
                  <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="review-edit-course-dept">
                    Course dept
                  </label>
                  <Input id="review-edit-course-dept" value={form.course_dept} onChange={(event) => setForm((prev) => ({ ...prev, course_dept: event.target.value }))} />
                </div>
                <div>
                  <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="review-edit-course-number">
                    Course number
                  </label>
                  <Input id="review-edit-course-number" value={form.course_number} onChange={(event) => setForm((prev) => ({ ...prev, course_number: event.target.value }))} />
                </div>
                <div>
                  <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="review-edit-course-suffix">
                    Course suffix
                  </label>
                  <Input id="review-edit-course-suffix" value={form.course_suffix} onChange={(event) => setForm((prev) => ({ ...prev, course_suffix: event.target.value }))} />
                </div>
                <div>
                  <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="review-edit-course-quarter">
                    Quarter
                  </label>
                  <Input id="review-edit-course-quarter" value={form.course_quarter} onChange={(event) => setForm((prev) => ({ ...prev, course_quarter: event.target.value.toUpperCase() }))} placeholder="WI" />
                </div>
                <div>
                  <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="review-edit-course-year2">
                    Year2
                  </label>
                  <Input id="review-edit-course-year2" value={form.course_year2} onChange={(event) => setForm((prev) => ({ ...prev, course_year2: event.target.value }))} placeholder="26" />
                </div>
              </div>
              <div>
                <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="review-edit-reason">
                  Reason
                </label>
                <Textarea id="review-edit-reason" value={form.reason} onChange={(event) => setForm((prev) => ({ ...prev, reason: event.target.value }))} placeholder="Why are you editing this change?" />
              </div>
              <div className="flex flex-wrap gap-3">
                <Button onClick={() => void runPreview()} disabled={busy !== null || !form.due_date}>
                  <Eye className="mr-2 h-4 w-4" />
                  {busy === "preview" ? "Previewing..." : "Preview changes"}
                </Button>
                <Button variant="secondary" onClick={() => void applyEdit()} disabled={busy !== null || !form.due_date}>
                  <Save className="mr-2 h-4 w-4" />
                  {busy === "apply" ? "Applying..." : mode === "proposal" ? "Apply proposal edit" : "Apply direct edit"}
                </Button>
              </div>
            </div>
          </Card>

          <div className="space-y-5">
            <Card className="bg-white/60 p-5">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Current item</p>
              <div className="mt-4 space-y-2 text-sm text-[#314051]">
                <p>Entity UID: {data.entity_uid}</p>
                <p>Family: {data.editable_event.family_name}</p>
                <p>Course: {formatCourseDisplay(data.editable_event as unknown as Record<string, unknown>)}</p>
              </div>
            </Card>

            {preview ? (
              <Card className="bg-white/60 p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Preview result</p>
                    <p className="mt-2 text-sm text-[#596270]">{preview.idempotent ? "No visible difference would be introduced." : "Review the edited payload before applying it."}</p>
                  </div>
                  <Badge tone="info">{formatStatusLabel(preview.mode)}</Badge>
                </div>
                <div className="mt-4 grid gap-3 lg:grid-cols-2">
                  <ReviewEditEventCard title="Base" event={preview.base} />
                  <ReviewEditEventCard title="Candidate After" event={preview.candidate_after} />
                </div>
                <div className="mt-4 space-y-1.5 text-sm text-[#314051]">
                  <p>Delta seconds: {preview.delta_seconds ?? "N/A"}</p>
                  {preview.will_reject_pending_change_ids.length > 0 ? <p>Will reject pending IDs: {preview.will_reject_pending_change_ids.join(", ")}</p> : null}
                </div>
              </Card>
            ) : (
              <EmptyState title="No preview yet" description="Preview the edit to inspect the resulting payload before applying it." />
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}
