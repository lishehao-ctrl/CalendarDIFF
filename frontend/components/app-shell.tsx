"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  BellDot,
  GitCompareArrows,
  LayoutDashboard,
  Link2,
  Pencil,
  type LucideIcon,
  Menu,
  Settings2,
  Sparkles,
  ChevronLeft,
  ChevronRight,
  X
} from "lucide-react";
import { LogoutButton } from "@/components/logout-button";
import { updateCurrentUser } from "@/lib/api/users";
import { getBrowserTimeZone } from "@/lib/browser-timezone";
import type { OnboardingStage } from "@/lib/types";
import { cn } from "@/lib/utils";

type SessionUser = {
  id: number;
  notify_email: string;
  timezone_name: string;
  timezone_source: "auto" | "manual";
  created_at: string;
  onboarding_stage: OnboardingStage;
  first_source_id: number | null;
};

const items: ReadonlyArray<{ href: string; label: string; icon: LucideIcon; description: string }> = [
  { href: "/", label: "Overview", icon: LayoutDashboard, description: "Status, queues, next step" },
  { href: "/sources", label: "Sources", icon: BellDot, description: "Connect and sync intake" },
  { href: "/review/changes", label: "Changes", icon: GitCompareArrows, description: "Approve detected updates" },
  { href: "/review/links", label: "Family", icon: Link2, description: "Manage families and raw types" },
  { href: "/manual", label: "Manual", icon: Pencil, description: "Add, edit, and delete events" },
  { href: "/settings", label: "Settings", icon: Settings2, description: "Timezone and notifications" }
] as const;

const DESKTOP_NAV_COLLAPSED_KEY = "calendardiff.desktop-nav-collapsed";

function NavContentWithItems({
  pathname,
  items,
  onNavigate,
  onboardingReady,
  collapsed,
  onToggleCollapse,
}: {
  pathname: string;
  items: ReadonlyArray<{ href: string; label: string; icon: LucideIcon; description: string }>;
  onNavigate?: () => void;
  onboardingReady: boolean;
  collapsed: boolean;
  onToggleCollapse?: () => void;
}) {
  return (
    <>
      <div className={cn("mb-6", collapsed ? "space-y-3" : "space-y-4")}>
        <div className={cn("flex items-start", collapsed ? "justify-center" : "justify-between gap-3")}>
          <div
            className={cn(
              "rounded-[1.6rem] bg-[linear-gradient(135deg,rgba(31,94,255,0.18),rgba(215,90,45,0.12))]",
              collapsed ? "flex h-14 w-14 items-center justify-center" : "flex flex-1 items-center gap-3 p-5"
            )}
          >
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-ink text-paper">
              <Sparkles className="h-5 w-5" />
            </div>
            {collapsed ? null : (
              <div>
                <p className="text-xs uppercase tracking-[0.24em] text-[#425061]">CalendarDIFF</p>
                <h1 className="mt-1 text-2xl font-semibold">Deadline Ops Console</h1>
              </div>
            )}
          </div>
          {onToggleCollapse ? (
            <button
              type="button"
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              onClick={onToggleCollapse}
              className={cn(
                "hidden h-11 w-11 items-center justify-center rounded-2xl border border-line/80 bg-white/75 text-ink transition hover:bg-white xl:flex",
                collapsed ? "shrink-0" : ""
              )}
            >
              {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
            </button>
          ) : null}
        </div>
        {!collapsed ? (
          <p className="text-sm leading-6 text-[#314051]">
            {onboardingReady
              ? "Keep intake, review, and deadline fixes in one calm workspace instead of spreading them across email and calendars."
              : "Finish setup once, then the review workspace will open with the right sources and term already in place."}
          </p>
        ) : null}
      </div>
      <nav className={cn("flex flex-1 flex-col", collapsed ? "gap-3" : "gap-2")}>
        {items.map(({ href, label, icon: Icon, description }) => {
          const active = href === "/" ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={href}
              href={href}
              aria-label={label}
              title={label}
              className={cn(
                "transition",
                collapsed
                  ? "flex h-14 w-14 items-center justify-center self-center rounded-2xl"
                  : "rounded-[1.25rem] px-4 py-4",
                active ? "bg-ink text-paper shadow-[0_16px_32px_rgba(20,32,44,0.18)]" : "text-[#314051] hover:bg-white/70"
              )}
              onClick={onNavigate}
            >
              <div className={cn("flex items-center", collapsed ? "justify-center" : "gap-3")}>
                <div
                  className={cn(
                    "flex h-10 w-10 items-center justify-center rounded-2xl",
                    active ? "bg-white/12" : "bg-[rgba(20,32,44,0.06)]"
                  )}
                >
                  <Icon className="h-4 w-4" />
                </div>
                {collapsed ? null : (
                  <div>
                    <div className="text-sm font-medium">{label}</div>
                    <div className={cn("mt-1 text-xs", active ? "text-white/70" : "text-[#7a8593]")}>{description}</div>
                  </div>
                )}
              </div>
            </Link>
          );
        })}
      </nav>
      <div className={cn("mt-6", collapsed ? "flex justify-center" : "space-y-3")}>
        {!collapsed ? (
          <div className="rounded-[1.25rem] border border-line/80 bg-white/55 p-4 text-sm text-[#596270]">
            {onboardingReady
              ? "Connect Canvas and Gmail from Sources, then work the resulting changes and link fixes from the two review lanes."
              : "Onboarding is required before the rest of the workspace unlocks."}
          </div>
        ) : null}
        <LogoutButton collapsed={collapsed} />
      </div>
    </>
  );
}

export function AppShell({
  children,
  sessionUser,
}: {
  children: React.ReactNode;
  sessionUser: SessionUser;
}) {
  const pathname = usePathname();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [desktopNavCollapsed, setDesktopNavCollapsed] = useState(false);
  const [timezoneSynced, setTimezoneSynced] = useState(false);
  const onboardingReady = sessionUser.onboarding_stage === "ready";
  const navItems = onboardingReady
    ? items
    : [
        {
          href: "/setup",
          label: "Setup",
          icon: Sparkles,
          description: "Connect sources and set the active term",
        },
      ] as const;

  useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    setDesktopNavCollapsed(window.localStorage.getItem(DESKTOP_NAV_COLLAPSED_KEY) === "true");
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(DESKTOP_NAV_COLLAPSED_KEY, desktopNavCollapsed ? "true" : "false");
  }, [desktopNavCollapsed]);

  useEffect(() => {
    if (timezoneSynced || sessionUser.timezone_source !== "auto") {
      return;
    }
    const browserTimeZone = getBrowserTimeZone();
    if (!browserTimeZone || browserTimeZone === sessionUser.timezone_name) {
      setTimezoneSynced(true);
      return;
    }

    let cancelled = false;

    void updateCurrentUser({
      timezone_name: browserTimeZone,
      timezone_source: "auto",
    })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) {
          setTimezoneSynced(true);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [sessionUser.timezone_name, sessionUser.timezone_source, timezoneSynced]);

  return (
    <div className="mx-auto flex min-h-screen max-w-[1500px] gap-6 p-4 md:p-6">
      <aside
        className={cn(
          "hidden shrink-0 flex-col rounded-[1.7rem] border border-line/80 bg-card p-5 shadow-[var(--shadow-panel)] xl:flex",
          desktopNavCollapsed ? "w-[92px]" : "w-80"
        )}
      >
        <NavContentWithItems
          pathname={pathname}
          items={navItems}
          onboardingReady={onboardingReady}
          collapsed={desktopNavCollapsed}
          onToggleCollapse={() => setDesktopNavCollapsed((current) => !current)}
        />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col gap-6">
        <div className="flex items-center justify-between rounded-[1.45rem] border border-line/70 bg-card px-4 py-3 shadow-[var(--shadow-panel)] xl:hidden">
          <div>
            <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">CalendarDIFF</p>
            <p className="mt-1 text-lg font-semibold">Deadline Ops</p>
          </div>
          <div className="flex items-center gap-2">
            <LogoutButton />
            <Dialog.Root open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
              <Dialog.Trigger asChild>
                <button aria-label="Open navigation" className="flex h-11 w-11 items-center justify-center rounded-2xl bg-ink text-paper">
                  <Menu className="h-5 w-5" />
                </button>
              </Dialog.Trigger>
              <Dialog.Portal>
                <Dialog.Overlay className="fixed inset-0 z-40 bg-[rgba(20,32,44,0.38)] backdrop-blur-sm" />
                <Dialog.Content className="fixed inset-y-0 left-0 z-50 w-[88vw] max-w-sm border-r border-line bg-card p-5 shadow-[var(--shadow-panel)]">
                  <Dialog.Title className="sr-only">Navigation menu</Dialog.Title>
                  <Dialog.Description className="sr-only">Navigate between overview, sources, review, family management, manual maintenance, and settings pages.</Dialog.Description>
                  <div className="mb-4 flex items-center justify-end">
                    <Dialog.Close asChild>
                      <button aria-label="Close navigation" className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[rgba(20,32,44,0.06)] text-ink">
                        <X className="h-4 w-4" />
                      </button>
                    </Dialog.Close>
                  </div>
                  <NavContentWithItems
                    pathname={pathname}
                    items={navItems}
                    onNavigate={() => setMobileNavOpen(false)}
                    onboardingReady={onboardingReady}
                    collapsed={false}
                  />
                </Dialog.Content>
              </Dialog.Portal>
            </Dialog.Root>
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}
