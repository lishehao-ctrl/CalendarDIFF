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
import { applyReviewEdit, getReviewChange, previewReviewEdit } from "@/lib/api/review";
import { formatDateTime, formatStatusLabel } from "@/lib/presenters";
import type { ReviewChange, ReviewEditApplyResponse, ReviewEditMode, ReviewEditPreviewResponse } from "@/lib/types";
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
      <p className="mt-2 font-medium text-ink">{event.title}</p>
      <p className="mt-1 text-xs text-[#6d7885]">{event.course_label}</p>
      <div className="mt-4 space-y-1.5">
        <p>Start: {formatDateTime(event.start_at_utc, "N/A")}</p>
        <p>End: {formatDateTime(event.end_at_utc, "N/A")}</p>
      </div>
    </div>
  );
}

export function ReviewChangeEditPageClient({ mode, changeId }: { mode: ReviewEditMode; changeId: number }) {
  const router = useRouter();
  const { data, loading, error } = useApiResource<ReviewChange>(() => getReviewChange(changeId), [changeId]);
  const [form, setForm] = useState({ due_at: "", title: "", course_label: "", reason: "" });
  const [preview, setPreview] = useState<ReviewEditPreviewResponse | null>(null);
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);

  useEffect(() => {
    if (!data) {
      return;
    }
    const editable = (data.after_json || data.before_json || {}) as Record<string, unknown>;
    setForm({
      due_at: typeof editable.start_at_utc === "string" ? editable.start_at_utc : "",
      title: typeof editable.title === "string" ? editable.title : "",
      course_label: typeof editable.course_label === "string" ? editable.course_label : "",
      reason: ""
    });
  }, [data]);

  const proposalEditable = useMemo(() => {
    if (!data) {
      return false;
    }
    return data.review_status === "pending" && data.change_type !== "removed";
  }, [data]);

  const pageTitle = useMemo(() => {
    if (!data) {
      return "Review change";
    }
    const afterTitle = data.after_json && typeof data.after_json["title"] === "string" ? data.after_json["title"] : null;
    const beforeTitle = data.before_json && typeof data.before_json["title"] === "string" ? data.before_json["title"] : null;
    return afterTitle || beforeTitle || data.event_uid;
  }, [data]);

  async function runPreview() {
    if (!data) {
      return;
    }
    setBusy("preview");
    setBanner(null);
    try {
      const payload = await previewReviewEdit({
        mode,
        target: { change_id: data.id },
        patch: {
          due_at: form.due_at,
          title: form.title || null,
          course_label: form.course_label || null
        },
        reason: form.reason || null
      });
      setPreview(payload);
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Preview failed" });
    } finally {
      setBusy(null);
    }
  }

  async function applyEdit() {
    if (!data) {
      return;
    }
    setBusy("apply");
    setBanner(null);
    try {
      const payload = await applyReviewEdit({
        mode,
        target: { change_id: data.id },
        patch: {
          due_at: form.due_at,
          title: form.title || null,
          course_label: form.course_label || null
        },
        reason: form.reason || null
      });
      setBanner({
        tone: "info",
        text: payload.mode === "proposal" ? "Proposal updated. Returning to review inbox..." : "Canonical event updated. Returning to review inbox..."
      });
      setTimeout(() => {
        router.push("/review/changes");
        router.refresh();
      }, 300);
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Apply failed" });
    } finally {
      setBusy(null);
    }
  }

  if (loading) {
    return <LoadingState label={mode === "proposal" ? "proposal edit" : "canonical edit"} />;
  }
  if (error) {
    return <ErrorState message={error} />;
  }
  if (!data) {
    return <EmptyState title="Change not found" description="This review change is unavailable or you do not have access to it." />;
  }
  if (mode === "proposal" && !proposalEditable) {
    return <ErrorState message="Proposal edits are only available for pending created or due-changed review items." />;
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
                ? "Adjust the pending proposal before it is approved into canonical state."
                : "Apply a direct canonical correction for this review item."}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={data.review_status}>{formatStatusLabel(data.review_status)}</Badge>
            <Button asChild size="sm" variant="ghost">
              <Link href="/review/changes">
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
                  Due at
                </label>
                <Input id="review-edit-due-at" value={form.due_at} onChange={(event) => setForm((prev) => ({ ...prev, due_at: event.target.value }))} />
              </div>
              <div>
                <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="review-edit-title">
                  Title
                </label>
                <Input id="review-edit-title" value={form.title} onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))} />
              </div>
              <div>
                <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="review-edit-course-label">
                  Course label
                </label>
                <Input id="review-edit-course-label" value={form.course_label} onChange={(event) => setForm((prev) => ({ ...prev, course_label: event.target.value }))} />
              </div>
              <div>
                <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="review-edit-reason">
                  Reason
                </label>
                <Textarea id="review-edit-reason" value={form.reason} onChange={(event) => setForm((prev) => ({ ...prev, reason: event.target.value }))} placeholder="Why are you editing this change?" />
              </div>
              <div className="flex flex-wrap gap-3">
                <Button onClick={() => void runPreview()} disabled={busy !== null || !form.due_at}>
                  <Eye className="mr-2 h-4 w-4" />
                  {busy === "preview" ? "Previewing..." : "Preview changes"}
                </Button>
                <Button variant="secondary" onClick={() => void applyEdit()} disabled={busy !== null || !form.due_at}>
                  <Save className="mr-2 h-4 w-4" />
                  {busy === "apply" ? "Applying..." : mode === "proposal" ? "Apply proposal edit" : "Apply canonical edit"}
                </Button>
              </div>
            </div>
          </Card>

          <div className="space-y-5">
            <Card className="bg-white/60 p-5">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Current item</p>
              <div className="mt-4 space-y-2 text-sm text-[#314051]">
                <p>Detected: {formatDateTime(data.detected_at)}</p>
                <p>Current status: {formatStatusLabel(data.review_status)}</p>
                <p>Change type: {formatStatusLabel(data.change_type)}</p>
              </div>
            </Card>

            {preview ? (
              <Card className="bg-white/60 p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Preview result</p>
                    <p className="mt-2 text-sm text-[#596270]">{preview.idempotent ? "No canonical difference would be introduced." : "Review the edited payload before applying it."}</p>
                  </div>
                  <Badge tone="info">{formatStatusLabel(preview.mode)}</Badge>
                </div>
                <div className="mt-4 grid gap-3 lg:grid-cols-2">
                  <ReviewEditEventCard title="Base" event={preview.base} />
                  <ReviewEditEventCard title="Candidate After" event={preview.candidate_after} />
                </div>
                <div className="mt-4 space-y-1.5 text-sm text-[#314051]">
                  <p>Delta seconds: {preview.delta_seconds ?? "N/A"}</p>
                  {preview.will_reject_pending_change_ids.length > 0 ? (
                    <p>Will reject pending IDs: {preview.will_reject_pending_change_ids.join(", ")}</p>
                  ) : null}
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
