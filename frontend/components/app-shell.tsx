"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  BellDot,
  CircleAlert,
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
import { updateSettingsProfile } from "@/lib/api/settings";
import { getBrowserTimeZone } from "@/lib/browser-timezone";
import { withBasePath } from "@/lib/demo-mode";
import { translate } from "@/lib/i18n/runtime";
import type { OnboardingStage } from "@/lib/types";
import { cn } from "@/lib/utils";
import { preloadWorkspaceLane } from "@/lib/workspace-preload";

type SessionUser = {
  id: number;
  notify_email: string;
  timezone_name: string;
  timezone_source: "auto" | "manual";
  created_at: string;
  onboarding_stage: OnboardingStage;
  first_source_id: number | null;
};

const items: ReadonlyArray<{ href: string; labelKey: string; icon: LucideIcon; descriptionKey: string }> = [
  { href: "/", labelKey: "shell.nav.overview.label", icon: LayoutDashboard, descriptionKey: "shell.nav.overview.description" },
  { href: "/sources", labelKey: "shell.nav.sources.label", icon: BellDot, descriptionKey: "shell.nav.sources.description" },
  { href: "/changes", labelKey: "shell.nav.changes.label", icon: GitCompareArrows, descriptionKey: "shell.nav.changes.description" },
  { href: "/families", labelKey: "shell.nav.families.label", icon: Link2, descriptionKey: "shell.nav.families.description" },
  { href: "/manual", labelKey: "shell.nav.manual.label", icon: Pencil, descriptionKey: "shell.nav.manual.description" },
  { href: "/settings", labelKey: "shell.nav.settings.label", icon: Settings2, descriptionKey: "shell.nav.settings.description" }
] as const;

const DESKTOP_NAV_COLLAPSED_KEY = "calendardiff.desktop-nav-collapsed";

function animatedTextBlock(collapsed: boolean, maxWidthClass: string) {
  return cn(
    "overflow-hidden transition-[max-width,opacity,transform,margin] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
    collapsed ? "pointer-events-none max-w-0 translate-x-2 opacity-0" : `${maxWidthClass} translate-x-0 opacity-100`
  );
}

function NavContentWithItems({
  pathname,
  items,
  collapsed,
  onToggleCollapse,
  onPrimeRoute,
  logoutRedirectTo = "/login",
}: {
  pathname: string;
  items: ReadonlyArray<{ href: string; labelKey: string; icon: LucideIcon; descriptionKey: string }>;
  collapsed: boolean;
  onToggleCollapse?: () => void;
  onPrimeRoute?: (href: string) => void;
  logoutRedirectTo?: string;
}) {
  return (
    <>
      <div className={cn("relative mb-6", collapsed ? "space-y-3" : "space-y-4")}>
        <div className={cn("flex items-start", collapsed ? "flex-col items-center gap-3" : "justify-between gap-3")}>
          <div
            className={cn(
              "rounded-[1.6rem] bg-[linear-gradient(135deg,rgba(31,94,255,0.18),rgba(215,90,45,0.12))] transition-all duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
              collapsed ? "flex h-12 w-12 items-center justify-center rounded-[1.35rem]" : "flex flex-1 items-center gap-3 p-5"
            )}
          >
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-ink text-paper">
              <Sparkles className="h-5 w-5" />
            </div>
            <div className={animatedTextBlock(collapsed, "max-w-[220px]")}>
              <p className="text-xs uppercase tracking-[0.24em] text-[#425061]">{translate("shell.brand")}</p>
              <h1 className="mt-1 text-2xl font-semibold">{translate("shell.title")}</h1>
            </div>
          </div>
          {onToggleCollapse ? (
            <button
              type="button"
              aria-label={collapsed ? translate("shell.expandSidebar") : translate("shell.collapseSidebar")}
              title={collapsed ? translate("shell.expandSidebar") : translate("shell.collapseSidebar")}
              onClick={onToggleCollapse}
              className={cn(
                "z-10 hidden items-center justify-center border border-line/80 bg-white/90 text-ink shadow-[0_10px_24px_rgba(20,32,44,0.08)] transition-all duration-300 hover:bg-white xl:flex",
                collapsed
                  ? "h-9 w-9 self-center rounded-full"
                  : "h-11 w-11 shrink-0 rounded-2xl"
              )}
            >
              {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
            </button>
          ) : null}
        </div>
      </div>
      <nav className={cn("flex flex-1 flex-col", collapsed ? "gap-3" : "gap-2")}>
        {items.map(({ href, labelKey, icon: Icon, descriptionKey }) => {
          const label = translate(labelKey);
          const description = translate(descriptionKey);
          const active = href === "/" ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={href}
              href={href}
              prefetch
              aria-label={label}
              title={label}
              onMouseEnter={() => onPrimeRoute?.(href)}
              onFocus={() => onPrimeRoute?.(href)}
              className={cn(
                "group relative transition-all duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
                collapsed
                  ? "flex h-12 w-12 items-center justify-center self-center rounded-2xl"
                  : "rounded-[1.25rem] px-4 py-4",
                active
                  ? "scale-[1.02] bg-ink text-paper shadow-[0_16px_32px_rgba(20,32,44,0.18)]"
                  : "text-[#314051] hover:bg-white/70 hover:scale-[1.02]",
                collapsed && active ? "ring-2 ring-[rgba(31,94,255,0.18)] ring-offset-2 ring-offset-card" : null
              )}
            >
              <div className={cn("flex items-center", collapsed ? "justify-center" : "gap-3")}>
                <div
                  className={cn(
                    "flex h-10 w-10 items-center justify-center rounded-2xl transition-all duration-300",
                    active ? "bg-white/12" : "bg-[rgba(20,32,44,0.06)]"
                  )}
                >
                  <Icon className="h-4 w-4" />
                </div>
                <div className={animatedTextBlock(collapsed, "max-w-[170px]")}>
                  <div className="text-sm font-medium">{label}</div>
                  <div className={cn("mt-1 text-xs", active ? "text-white/70" : "text-[#7a8593]")}>{description}</div>
                </div>
              </div>
              {collapsed ? (
                <span
                  className={cn(
                    "pointer-events-none absolute left-full top-1/2 ml-3 -translate-y-1/2 rounded-full border border-line/80 bg-white px-3 py-1.5 text-xs font-medium text-ink opacity-0 shadow-[0_12px_30px_rgba(20,32,44,0.12)] transition-all duration-200",
                    "group-hover:translate-x-1 group-hover:opacity-100 group-focus-visible:translate-x-1 group-focus-visible:opacity-100"
                  )}
                >
                  {label}
                </span>
              ) : null}
            </Link>
          );
        })}
      </nav>
      <div className={cn("mt-6", collapsed ? "flex justify-center" : "space-y-3")}>
        <LogoutButton collapsed={collapsed} redirectTo={logoutRedirectTo} />
      </div>
    </>
  );
}

export function AppShell({
  children,
  sessionUser,
  basePath = "",
}: {
  children: React.ReactNode;
  sessionUser: SessionUser;
  basePath?: string;
}) {
  const pathname = usePathname();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [desktopNavCollapsed, setDesktopNavCollapsed] = useState(false);
  const [timezoneSynced, setTimezoneSynced] = useState(false);
  const onboardingReady = sessionUser.onboarding_stage === "ready";
  const navItems = items.map((item) => ({ ...item, href: withBasePath(basePath, item.href) }));
  const primeRoute = useCallback((href: string) => {
    preloadWorkspaceLane(href);
  }, []);

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

    void updateSettingsProfile({
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

  useEffect(() => {
    if (!onboardingReady || typeof window === "undefined") {
      return;
    }

    const warmRoutes = [withBasePath(basePath, "/sources"), withBasePath(basePath, "/changes"), withBasePath(basePath, "/settings")];
    const runWarmup = () => {
      for (const href of warmRoutes) {
        primeRoute(href);
      }
    };

    const requestIdle = typeof window.requestIdleCallback === "function" ? window.requestIdleCallback.bind(window) : null;
    if (requestIdle) {
      const idleId = requestIdle(() => runWarmup(), { timeout: 1200 });
      return () => window.cancelIdleCallback?.(idleId);
    }

    const timeoutId = globalThis.setTimeout(runWarmup, 350);
    return () => globalThis.clearTimeout(timeoutId);
  }, [basePath, onboardingReady, primeRoute]);

  return (
    <div className="mx-auto flex min-h-screen max-w-[1500px] gap-6 p-4 md:p-6">
      <aside
        className={cn(
          "hidden shrink-0 flex-col overflow-visible rounded-[1.7rem] border border-line/80 bg-card p-5 shadow-[var(--shadow-panel)] transition-[width,padding] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] xl:flex",
          desktopNavCollapsed ? "w-[76px] p-3" : "w-80"
        )}
      >
        <NavContentWithItems
          pathname={pathname}
          items={navItems}
          collapsed={desktopNavCollapsed}
          onToggleCollapse={() => setDesktopNavCollapsed((current) => !current)}
          onPrimeRoute={primeRoute}
          logoutRedirectTo={basePath ? withBasePath(basePath, "/") : "/login"}
        />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col gap-6">
        <div className="flex items-center justify-between rounded-[1.45rem] border border-line/70 bg-card px-4 py-3 shadow-[var(--shadow-panel)] xl:hidden">
          <div>
            <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">{translate("shell.brand")}</p>
            <p className="mt-1 text-lg font-semibold">{translate("shell.title")}</p>
          </div>
          <div className="flex items-center gap-2">
            <LogoutButton redirectTo={basePath ? withBasePath(basePath, "/") : "/login"} />
            <Dialog.Root open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
              <Dialog.Trigger asChild>
                <button aria-label={translate("shell.openNavigation")} className="flex h-11 w-11 items-center justify-center rounded-2xl bg-ink text-paper">
                  <Menu className="h-5 w-5" />
                </button>
              </Dialog.Trigger>
              <Dialog.Portal>
                <Dialog.Overlay className="fixed inset-0 z-40 bg-[rgba(20,32,44,0.38)] backdrop-blur-sm" />
                <Dialog.Content className="fixed inset-y-0 left-0 z-50 w-[88vw] max-w-sm border-r border-line bg-card p-5 shadow-[var(--shadow-panel)]">
                  <Dialog.Title className="sr-only">{translate("shell.openNavigation")}</Dialog.Title>
                  <Dialog.Description className="sr-only">{translate("shell.navigateDescription")}</Dialog.Description>
                  <div className="mb-4 flex items-center justify-end">
                    <Dialog.Close asChild>
                      <button aria-label={translate("shell.closeNavigation")} className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[rgba(20,32,44,0.06)] text-ink">
                        <X className="h-4 w-4" />
                      </button>
                    </Dialog.Close>
                  </div>
                  <NavContentWithItems
                    pathname={pathname}
                    items={navItems}
                    collapsed={false}
                    onPrimeRoute={primeRoute}
                    logoutRedirectTo={basePath ? withBasePath(basePath, "/") : "/login"}
                  />
                </Dialog.Content>
              </Dialog.Portal>
            </Dialog.Root>
          </div>
        </div>
        <div className="animate-surface-enter flex flex-col gap-3 rounded-[1.45rem] border border-line/70 bg-card px-4 py-4 shadow-[var(--shadow-panel)] md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">{translate("shell.workspaceStatus")}</p>
          </div>
          <div className="flex flex-wrap gap-2 text-sm text-[#314051]">
            <span className="rounded-full border border-line/80 bg-white/80 px-3 py-1.5">{sessionUser.notify_email}</span>
            <span className="rounded-full border border-line/80 bg-white/80 px-3 py-1.5">{sessionUser.timezone_name}</span>
            <span className={cn(
              "inline-flex items-center gap-2 rounded-full border px-3 py-1.5",
              onboardingReady ? "border-[rgba(77,124,15,0.18)] bg-[rgba(77,124,15,0.08)] text-[#3f5f12]" : "border-[rgba(215,90,45,0.18)] bg-[rgba(215,90,45,0.08)] text-[#8a472d]",
            )}>
              <CircleAlert className="h-4 w-4" />
              {onboardingReady ? translate("shell.systemReady") : translate("onboarding.onboardingRequired")}
            </span>
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}
