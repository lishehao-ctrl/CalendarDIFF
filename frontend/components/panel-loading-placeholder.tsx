import { Card } from "@/components/ui/card";
import {
  workbenchPanelClassName,
  workbenchSkeletonBlockClassName,
  workbenchSkeletonPanelClassName,
  workbenchStateSurfaceClassName,
} from "@/lib/workbench-styles";
import { cn } from "@/lib/utils";

export function PanelLoadingPlaceholder({
  eyebrow,
  title,
  summary,
  rows = 3,
  className,
}: {
  eyebrow?: string;
  title?: string;
  summary?: string;
  rows?: number;
  className?: string;
}) {
  return (
    <Card className={cn(workbenchPanelClassName("secondary", "animate-surface-enter p-5"), className)}>
      {eyebrow || title || summary ? (
        <div className={workbenchStateSurfaceClassName("neutral", "mb-5 space-y-2 px-4 py-3")}>
          {eyebrow ? <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{eyebrow}</p> : null}
          {title ? <h3 className="text-lg font-semibold text-ink">{title}</h3> : null}
          {summary ? <p className="max-w-2xl text-sm text-[#596270]">{summary}</p> : null}
        </div>
      ) : null}
      <div className="space-y-3">
        {Array.from({ length: rows }).map((_, index) => (
          <div key={index} className={workbenchSkeletonPanelClassName("rounded-[1rem] p-4")}>
            <div className={workbenchSkeletonBlockClassName("h-3 w-28 opacity-90")} />
            <div className={workbenchSkeletonBlockClassName("mt-3 h-6 w-2/5 opacity-90")} />
            <div className={workbenchSkeletonBlockClassName("mt-3 h-3 w-4/5 opacity-90")} />
          </div>
        ))}
      </div>
    </Card>
  );
}
