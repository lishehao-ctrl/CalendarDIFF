import { Badge } from "@/components/ui/badge";

export function PageHeader({
  eyebrow,
  title,
  description,
  badge,
  badgeTone = "info",
  titleAs = "h1",
}: {
  eyebrow: string;
  title: string;
  description: string;
  badge?: string;
  badgeTone?: string;
  titleAs?: "h1" | "h2";
}) {
  const HeadingTag = titleAs;
  return (
    <header className="animate-header-enter rounded-[1.15rem] border border-line/80 bg-card px-5 py-4 shadow-[var(--shadow-panel)]">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-3xl">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">{eyebrow}</p>
          <HeadingTag className="mt-1 text-[1.65rem] font-semibold leading-tight text-ink">{title}</HeadingTag>
          <p className="mt-2 text-sm leading-6 text-[#596270]">{description}</p>
        </div>
        {badge ? <Badge tone={badgeTone}>{badge}</Badge> : null}
      </div>
    </header>
  );
}
