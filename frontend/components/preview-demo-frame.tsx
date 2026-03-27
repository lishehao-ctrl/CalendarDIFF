"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowRight, Eye, GitCompareArrows, Settings2, Sparkles, Wrench } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { translate } from "@/lib/i18n/runtime";
import { cn } from "@/lib/utils";

const demoStops = [
  {
    key: "changes",
    href: "/preview/changes",
    icon: GitCompareArrows,
    match: (pathname: string) => pathname.startsWith("/preview/changes"),
    titleKey: "previewDemo.stops.changes.title",
    summaryKey: "previewDemo.stops.changes.summary",
  },
  {
    key: "sources",
    href: "/preview/sources/2",
    icon: Wrench,
    match: (pathname: string) => pathname.startsWith("/preview/sources"),
    titleKey: "previewDemo.stops.sources.title",
    summaryKey: "previewDemo.stops.sources.summary",
  },
  {
    key: "assistant",
    href: "/preview/agent",
    icon: Sparkles,
    match: (pathname: string) => pathname.startsWith("/preview/agent"),
    titleKey: "previewDemo.stops.assistant.title",
    summaryKey: "previewDemo.stops.assistant.summary",
  },
  {
    key: "settings",
    href: "/preview/settings",
    icon: Settings2,
    match: (pathname: string) => pathname.startsWith("/preview/settings"),
    titleKey: "previewDemo.stops.settings.title",
    summaryKey: "previewDemo.stops.settings.summary",
  },
] as const;

export function PreviewDemoFrame({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/preview";
  const showRibbon = pathname !== "/preview";

  if (!showRibbon) {
    return <>{children}</>;
  }

  return (
    <div className="space-y-4">
      <Card className="animate-header-enter overflow-hidden border-cobalt/15 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.12),transparent_35%),linear-gradient(180deg,rgba(255,255,255,0.98),rgba(246,249,255,0.95))] p-4 md:p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("previewDemo.ribbonEyebrow")}</p>
            <h2 className="mt-2 text-lg font-semibold text-ink">{translate("previewDemo.ribbonTitle")}</h2>
            <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("previewDemo.ribbonSummary")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="info">{translate("previewDemo.badge")}</Badge>
            <Button asChild size="sm" variant="ghost">
              <Link href="/preview">
                {translate("previewDemo.backToHome")}
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </div>
        </div>

        <div className="mt-4 grid gap-3 xl:grid-cols-4">
          {demoStops.map((stop) => {
            const Icon = stop.icon;
            const active = stop.match(pathname);
            return (
              <Link
                key={stop.key}
                href={stop.href}
                className={cn(
                  "group rounded-[1.15rem] border p-4 transition-all duration-300",
                  active
                    ? "border-cobalt/25 bg-[rgba(31,94,255,0.08)] shadow-[0_10px_24px_rgba(31,94,255,0.08)]"
                    : "border-line/80 bg-white/78 hover:-translate-y-0.5 hover:bg-white",
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[rgba(20,32,44,0.06)] text-ink">
                        <Icon className="h-4 w-4" />
                      </div>
                      <p className="text-sm font-medium text-ink">{translate(stop.titleKey)}</p>
                    </div>
                    <p className="mt-3 text-sm leading-6 text-[#596270]">{translate(stop.summaryKey)}</p>
                  </div>
                  {active ? <Eye className="mt-0.5 h-4 w-4 shrink-0 text-cobalt" /> : <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-[#6d7885] transition-transform group-hover:translate-x-0.5" />}
                </div>
              </Link>
            );
          })}
        </div>
      </Card>
      {children}
    </div>
  );
}
