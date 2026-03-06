import type { ReviewChange } from "@/lib/types";

const shortFormatter = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit"
});

export function formatDateTime(value: string | null | undefined, fallback = "Not available") {
  if (!value) {
    return fallback;
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return fallback;
  }

  return shortFormatter.format(date);
}

export function formatStatusLabel(value: string | null | undefined, fallback = "Unknown") {
  if (!value) {
    return fallback;
  }
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function extractEventTitle(payload: Record<string, unknown> | null | undefined, fallback: string) {
  if (!payload) {
    return fallback;
  }

  for (const key of ["title", "summary", "name", "course_label"]) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }

  return fallback;
}

export function extractEventSubtitle(payload: Record<string, unknown> | null | undefined) {
  if (!payload) {
    return null;
  }

  const parts: string[] = [];
  const course = payload.course_label;
  const due = payload.due_at;
  const location = payload.location;

  if (typeof course === "string" && course.trim()) {
    parts.push(course.trim());
  }
  if (typeof due === "string" && due.trim()) {
    parts.push(due.trim());
  }
  if (typeof location === "string" && location.trim()) {
    parts.push(location.trim());
  }

  return parts.length > 0 ? parts.join(" · ") : null;
}

export function summarizeChange(change: ReviewChange) {
  const beforeTitle = extractEventTitle(change.before_json, change.event_uid);
  const afterTitle = extractEventTitle(change.after_json, beforeTitle);
  const subtitle = extractEventSubtitle(change.after_json) || extractEventSubtitle(change.before_json);

  return {
    title: afterTitle,
    beforeTitle,
    afterTitle,
    subtitle
  };
}

export function sourceDescriptor(source: {
  provider?: string | null;
  source_kind?: string | null;
  source_id: number;
}) {
  const label = source.provider || source.source_kind || "source";
  return `${label}#${source.source_id}`;
}
