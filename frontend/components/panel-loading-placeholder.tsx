import { Card } from "@/components/ui/card";
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
    <Card className={cn("animate-surface-enter p-5", className)}>
      {eyebrow || title || summary ? (
        <div className="mb-5 space-y-2">
          {eyebrow ? <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{eyebrow}</p> : null}
          {title ? <h3 className="text-lg font-semibold text-ink">{title}</h3> : null}
          {summary ? <p className="max-w-2xl text-sm text-[#596270]">{summary}</p> : null}
        </div>
      ) : null}
      <div className="space-y-3 animate-pulse">
        {Array.from({ length: rows }).map((_, index) => (
          <div key={index} className="rounded-[1rem] border border-line/70 bg-white/65 p-4">
            <div className="h-3 w-28 rounded-full bg-[rgba(20,32,44,0.08)]" />
            <div className="mt-3 h-6 w-2/5 rounded-full bg-[rgba(20,32,44,0.08)]" />
            <div className="mt-3 h-3 w-4/5 rounded-full bg-[rgba(20,32,44,0.08)]" />
          </div>
        ))}
      </div>
    </Card>
  );
}
