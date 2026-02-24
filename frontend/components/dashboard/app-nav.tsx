import { BellRing, ListChecks, Workflow, FlaskConical } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type AppNavProps = {
  current: "processing" | "feed" | "runs" | "dev";
  activeUserId: number | null;
  activeInputId: number | null;
  showDev?: boolean;
};

type NavItem = {
  key: "processing" | "feed" | "runs" | "dev";
  label: string;
  icon: LucideIcon;
  path: "/ui/processing" | "/ui/feed" | "/ui/runs" | "/ui/dev";
};

const NAV_ITEMS: NavItem[] = [
  { key: "processing", label: "Processing", icon: Workflow, path: "/ui/processing" },
  { key: "feed", label: "Feed", icon: BellRing, path: "/ui/feed" },
  { key: "runs", label: "Runs", icon: ListChecks, path: "/ui/runs" },
  { key: "dev", label: "Dev", icon: FlaskConical, path: "/ui/dev" },
];

export function AppNav({ current, activeUserId, activeInputId, showDev = false }: AppNavProps) {
  const visibleItems = showDev ? NAV_ITEMS : NAV_ITEMS.filter((item) => item.key !== "dev");
  return (
    <nav className="flex flex-wrap gap-2">
      {visibleItems.map((item) => {
        const Icon = item.icon;
        const href = buildHref(item.path, activeUserId, activeInputId);
        return (
          <Button
            key={item.key}
            variant={item.key === current ? "default" : "secondary"}
            size="sm"
            asChild
            className={cn(item.key === current ? "pointer-events-none" : "")}
          >
            <a href={href}>
              <Icon className="mr-2 h-4 w-4" />
              {item.label}
            </a>
          </Button>
        );
      })}
    </nav>
  );
}

function buildHref(path: string, activeUserId: number | null, activeInputId: number | null): string {
  const params = new URLSearchParams();
  if (activeUserId !== null) {
    params.set("user_id", String(activeUserId));
  }
  if (activeInputId !== null) {
    params.set("input_id", String(activeInputId));
  }
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}
