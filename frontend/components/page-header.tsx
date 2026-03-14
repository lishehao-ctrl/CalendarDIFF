import { Badge } from "@/components/ui/badge";

export function PageHeader({
  eyebrow,
  title,
  description,
  badge
}: {
  eyebrow: string;
  title: string;
  description: string;
  badge?: string;
}) {
  return (
    <header className="relative overflow-hidden rounded-[1.6rem] border border-line/80 bg-card px-6 py-6 shadow-[var(--shadow-panel)]">
      <div className="absolute inset-y-0 right-0 w-48 bg-[radial-gradient(circle_at_center,rgba(31,94,255,0.12),transparent_65%)]" />
      <div className="relative flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-3xl">
          <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">{eyebrow}</p>
          <h2 className="mt-3 text-2xl font-semibold text-ink md:text-[2rem]">{title}</h2>
          <p className="mt-3 text-sm leading-6 text-[#596270]">{description}</p>
        </div>
        {badge ? <Badge tone="info">{badge}</Badge> : null}
      </div>
    </header>
  );
}
