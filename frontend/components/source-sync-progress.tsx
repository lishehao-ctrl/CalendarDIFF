"use client";

import { cn } from "@/lib/utils";
import type { SyncProgress } from "@/lib/types";

export function SourceSyncProgress({
  progress,
  className,
}: {
  progress: SyncProgress | null | undefined;
  className?: string;
}) {
  if (!progress) {
    return null;
  }

  const current = typeof progress.current === "number" ? progress.current : null;
  const total = typeof progress.total === "number" ? progress.total : null;
  const percent = typeof progress.percent === "number" ? Math.max(0, Math.min(100, progress.percent)) : null;
  const hasBar = current !== null && total !== null && total > 0 && percent !== null;
  const unit = progress.unit ? ` ${progress.unit}` : "";

  return (
    <div className={cn("rounded-[1.15rem] border border-[rgba(31,94,255,0.14)] bg-[rgba(31,94,255,0.05)] px-4 py-3", className)}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-ink">{progress.label}</p>
          {progress.detail ? <p className="mt-1 text-xs leading-5 text-[#596270]">{progress.detail}</p> : null}
        </div>
        {current !== null && total !== null ? (
          <p className="whitespace-nowrap text-xs font-medium text-cobalt">
            {current}/{total}
            {unit}
          </p>
        ) : null}
      </div>
      {hasBar ? (
        <div className="mt-3">
          <div className="h-2 rounded-full bg-white/90">
            <div
              aria-hidden="true"
              className="progress-sheen h-2 rounded-full bg-cobalt transition-all duration-500"
              style={{ width: `${percent}%` }}
            />
          </div>
          <div className="mt-2 flex items-center justify-between text-[11px] uppercase tracking-[0.16em] text-[#6d7885]">
            <span>{progress.phase.replaceAll("_", " ")}</span>
            <span>{percent.toFixed(percent % 1 === 0 ? 0 : 1)}%</span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
