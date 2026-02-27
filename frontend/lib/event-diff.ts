import { ChangeRecord } from "@/lib/types";

type DiffFieldKey =
  | "title"
  | "course_label"
  | "start_at_utc"
  | "end_at_utc"
  | "due_at"
  | "location"
  | "description";

type DiffFieldSpec = {
  key: DiffFieldKey;
  label: string;
};

const DIFF_FIELD_SPECS: readonly DiffFieldSpec[] = [
  { key: "title", label: "Title" },
  { key: "course_label", label: "Course" },
  { key: "start_at_utc", label: "Start" },
  { key: "end_at_utc", label: "End" },
  { key: "due_at", label: "Due" },
  { key: "location", label: "Location" },
  { key: "description", label: "Description" },
] as const;

const VALUE_FALLBACK = "n/a";
const MAX_PREVIEW_TEXT = 220;

export type NormalizedChangeType = "created" | "removed" | "due_changed";

export type DiffBucketCounts = {
  added: number;
  removed: number;
  modified: number;
};

export type FieldDiff = {
  field: DiffFieldKey;
  label: string;
  before: string;
  after: string;
};

export type DiffSummaryField = {
  field: DiffFieldKey;
  label: string;
  value: string;
};

export type ChangeDiffViewModel = {
  normalizedType: NormalizedChangeType;
  title: string;
  courseLabel: string;
  beforeSummary: DiffSummaryField[];
  afterSummary: DiffSummaryField[];
  fieldDiffs: FieldDiff[];
};

export function normalizeChangeType(value: string): NormalizedChangeType {
  const normalized = value.trim().toLowerCase();
  if (normalized === "created") {
    return "created";
  }
  if (normalized === "removed") {
    return "removed";
  }
  return "due_changed";
}

export function deriveFieldDiffs(
  beforeJson: Record<string, unknown> | null,
  afterJson: Record<string, unknown> | null,
): FieldDiff[] {
  return DIFF_FIELD_SPECS.flatMap((spec) => {
    const beforeRaw = readField(beforeJson, spec.key);
    const afterRaw = readField(afterJson, spec.key);
    const beforeComparable = normalizeComparableValue(beforeRaw);
    const afterComparable = normalizeComparableValue(afterRaw);
    if (beforeComparable === afterComparable) {
      return [];
    }
    return [
      {
        field: spec.key,
        label: spec.label,
        before: formatDisplayValue(beforeRaw),
        after: formatDisplayValue(afterRaw),
      },
    ];
  });
}

export function computeOverviewCounts(changes: ChangeRecord[]): DiffBucketCounts {
  return changes.reduce<DiffBucketCounts>(
    (counts, change) => {
      const type = normalizeChangeType(change.change_type);
      if (type === "created") {
        counts.added += 1;
      } else if (type === "removed") {
        counts.removed += 1;
      } else {
        counts.modified += 1;
      }
      return counts;
    },
    { added: 0, removed: 0, modified: 0 },
  );
}

export function toChangeDiffViewModel(change: ChangeRecord): ChangeDiffViewModel {
  const beforeJson = asRecord(change.before_json);
  const afterJson = asRecord(change.after_json);
  const normalizedType = normalizeChangeType(change.change_type);

  return {
    normalizedType,
    title:
      readString(readField(afterJson, "title")) ??
      readString(readField(beforeJson, "title")) ??
      change.event_uid,
    courseLabel:
      readString(readField(afterJson, "course_label")) ??
      readString(readField(beforeJson, "course_label")) ??
      "Unknown course",
    beforeSummary: toSummaryFields(beforeJson),
    afterSummary: toSummaryFields(afterJson),
    fieldDiffs: deriveFieldDiffs(beforeJson, afterJson),
  };
}

function toSummaryFields(payload: Record<string, unknown> | null): DiffSummaryField[] {
  return DIFF_FIELD_SPECS.map((spec) => ({
    field: spec.key,
    label: spec.label,
    value: formatDisplayValue(readField(payload, spec.key)),
  }));
}

function readField(payload: Record<string, unknown> | null, key: DiffFieldKey): unknown {
  if (!payload) {
    return null;
  }
  return payload[key];
}

function normalizeComparableValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map((item) => normalizeComparableValue(item)).join("|");
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function formatDisplayValue(value: unknown): string {
  if (value === null || value === undefined) {
    return VALUE_FALLBACK;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) {
      return VALUE_FALLBACK;
    }
    if (trimmed.length <= MAX_PREVIEW_TEXT) {
      return trimmed;
    }
    return `${trimmed.slice(0, MAX_PREVIEW_TEXT).trimEnd()}...`;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    const compact = value
      .map((item) => normalizeComparableValue(item))
      .filter((item) => item.length > 0)
      .join(", ");
    return compact || VALUE_FALLBACK;
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function readString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed || null;
}
