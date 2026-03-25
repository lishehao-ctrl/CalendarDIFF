import { cn } from "@/lib/utils";

export function workbenchPanelClassName(
  tone: "primary" | "secondary" | "quiet" = "secondary",
  className?: string,
) {
  return cn(
    tone === "primary"
      ? "workbench-surface-primary"
      : tone === "quiet"
        ? "workbench-surface-quiet"
        : "workbench-surface-secondary",
    className,
  );
}

export function workbenchSupportPanelClassName(
  tone: "default" | "quiet" | "info" | "error" = "default",
  className?: string,
) {
  return cn(
    "rounded-[1.1rem] border",
    tone === "quiet"
      ? "workbench-support-panel--quiet"
      : tone === "info"
        ? "workbench-support-panel--info"
        : tone === "error"
          ? "workbench-support-panel--error"
          : "workbench-support-panel",
    className,
  );
}

export function workbenchQueueRowClassName({
  selected = false,
  checked = false,
  className,
}: {
  selected?: boolean;
  checked?: boolean;
  className?: string;
}) {
  return cn(
    "workbench-queue-row interactive-lift",
    selected
      ? "workbench-queue-row--selected"
      : checked
        ? "workbench-queue-row--checked"
        : "workbench-queue-row--idle",
    className,
  );
}

export function workbenchEmptyClassName(className?: string) {
  return cn("workbench-empty-card", className);
}

export function workbenchStateSurfaceClassName(
  tone: "neutral" | "info" | "error" = "neutral",
  className?: string,
) {
  return cn(
    "workbench-state-surface",
    tone === "info"
      ? "workbench-state-surface--info"
      : tone === "error"
        ? "workbench-state-surface--error"
        : "workbench-state-surface--neutral",
    className,
  );
}

export function workbenchSkeletonPanelClassName(className?: string) {
  return cn("workbench-skeleton-panel progress-sheen", className);
}

export function workbenchSkeletonBlockClassName(className?: string) {
  return cn("workbench-skeleton-block", className);
}
