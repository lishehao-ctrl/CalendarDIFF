import type { ChangeItem } from "@/lib/types";

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

export function formatSemanticDue(payload: Record<string, unknown> | null | undefined, fallback = "Not available") {
  if (!payload) {
    return fallback;
  }
  const dueDate = typeof payload.due_date === "string" ? payload.due_date.trim() : "";
  if (!dueDate) {
    return fallback;
  }
  const dueTime = typeof payload.due_time === "string" ? payload.due_time.trim() : "";
  const precision = typeof payload.time_precision === "string" ? payload.time_precision : "datetime";
  if (!dueTime || precision === "date_only") {
    return dueDate;
  }
  return `${dueDate} ${dueTime}`;
}

export function formatCourseDisplay(payload: Record<string, unknown> | null | undefined, fallback = "Unknown course") {
  if (!payload) {
    return fallback;
  }
  if (typeof payload.course_display === "string" && payload.course_display.trim()) {
    return payload.course_display.trim();
  }
  const dept = typeof payload.course_dept === "string" ? payload.course_dept.trim().toUpperCase() : "";
  const number = typeof payload.course_number === "number" ? String(payload.course_number) : "";
  const suffix = typeof payload.course_suffix === "string" ? payload.course_suffix.trim().toUpperCase() : "";
  const quarter = typeof payload.course_quarter === "string" ? payload.course_quarter.trim().toUpperCase() : "";
  const year2 = typeof payload.course_year2 === "number" ? String(payload.course_year2).padStart(2, "0") : "";
  if (!dept || !number) {
    return fallback;
  }
  const base = `${dept} ${number}${suffix}`.trim();
  if (quarter && year2) {
    return `${base} ${quarter}${year2}`;
  }
  return base;
}

export function extractEventTitle(payload: Record<string, unknown> | null | undefined, fallback: string) {
  if (!payload) {
    return fallback;
  }

  for (const key of ["event_name", "raw_type"]) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }

  return formatCourseDisplay(payload, fallback);
}

export function extractEventSubtitle(payload: Record<string, unknown> | null | undefined) {
  if (!payload) {
    return null;
  }

  const parts: string[] = [];
  const course = formatCourseDisplay(payload, "");
  const due = formatSemanticDue(payload, "");
  const rawType = payload.raw_type;

  if (course) {
    parts.push(course);
  }
  if (typeof rawType === "string" && rawType.trim()) {
    parts.push(rawType.trim());
  }
  if (due) {
    parts.push(due);
  }

  return parts.length > 0 ? parts.join(" · ") : null;
}

export function summarizeChange(change: ChangeItem) {
  const beforeTitle = change.before_display?.display_label || change.entity_uid;
  const afterTitle = change.after_display?.display_label || beforeTitle;
  const subtitle = formatSemanticDue(change.after_event as unknown as Record<string, unknown>, "") || formatSemanticDue(change.before_event as unknown as Record<string, unknown>, "");

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
  const provider = typeof source.provider === "string" ? source.provider.trim().toLowerCase() : "";
  if (provider === "ics") {
    return "Canvas ICS";
  }
  if (provider === "gmail") {
    return "Gmail";
  }
  if (provider) {
    return formatStatusLabel(provider);
  }

  const sourceKind = typeof source.source_kind === "string" ? source.source_kind.trim() : "";
  if (sourceKind) {
    return formatStatusLabel(sourceKind);
  }

  return `Source #${source.source_id}`;
}

export function sourceKindDescriptor(value: string | null | undefined) {
  if (!value) {
    return null;
  }
  return `${formatStatusLabel(value)} source`;
}
