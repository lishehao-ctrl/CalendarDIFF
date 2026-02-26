import { BellRing, Workflow } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type AppNavProps = {
  current: AppNavCurrent;
  activeInputId: number | null;
  density?: AppNavDensity;
};

export type AppNavCurrent = "onboarding" | "processing" | "feed" | "emails";
export type AppNavDensity = "comfortable" | "compact";

type NavItem = {
  key: AppNavCurrent;
  label: string;
  icon: LucideIcon;
  path: "/ui/onboarding" | "/ui/processing" | "/ui/feed" | "/ui/emails/review";
};

const NAV_ITEMS: NavItem[] = [
  { key: "onboarding", label: "Onboarding", icon: Workflow, path: "/ui/onboarding" },
  { key: "processing", label: "Processing", icon: Workflow, path: "/ui/processing" },
  { key: "feed", label: "Feed", icon: BellRing, path: "/ui/feed" },
  { key: "emails", label: "Email Review", icon: BellRing, path: "/ui/emails/review" },
];

export function AppNav({ current, activeInputId, density = "comfortable" }: AppNavProps) {
  const visibleItems = NAV_ITEMS;
  return (
    <nav
      aria-label="Workspace navigation"
      className={cn(
        "flex w-full items-center gap-1 overflow-x-auto rounded-2xl border border-line bg-white/85 p-1 shadow-card",
        density === "compact" ? "max-w-fit" : ""
      )}
    >
      {visibleItems.map((item) => {
        const Icon = item.icon;
        const href = buildHref(item.path, activeInputId);
        const isCurrent = item.key === current;
        return (
          <Button
            key={item.key}
            variant={isCurrent ? "default" : "ghost"}
            size="sm"
            asChild
            className={cn(
              "min-w-fit",
              isCurrent ? "pointer-events-none shadow-sm" : "text-muted hover:text-ink",
              density === "compact" ? "h-8 px-2.5 text-xs" : "h-9 px-3"
            )}
          >
            <a href={href} aria-current={isCurrent ? "page" : undefined}>
              <Icon className={cn("mr-2 h-4 w-4", density === "compact" ? "mr-1.5 h-3.5 w-3.5" : "")} />
              {item.label}
            </a>
          </Button>
        );
      })}
    </nav>
  );
}

function buildHref(path: string, activeInputId: number | null): string {
  const params = new URLSearchParams();
  if (activeInputId !== null) {
    params.set("input_id", String(activeInputId));
  }
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}
