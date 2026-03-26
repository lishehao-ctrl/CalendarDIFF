"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
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
import { Sheet, SheetContent, SheetDescription, SheetDismissButton, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { updateSettingsProfile } from "@/lib/api/settings";
import { getBrowserTimeZone } from "@/lib/browser-timezone";
import { withBasePath } from "@/lib/demo-mode";
import { translate } from "@/lib/i18n/runtime";
import { useLocale } from "@/lib/i18n/use-locale";
import { useResponsiveTier } from "@/lib/use-responsive-tier";
import type { OnboardingStage } from "@/lib/types";
import { cn } from "@/lib/utils";
import { preloadWorkspaceLane } from "@/lib/workspace-preload";

type SessionUser = {
  id: number;
  email: string;
  language_code: "en" | "zh-CN";
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
      <div className={cn("relative mb-4", collapsed ? "space-y-2" : "space-y-3")}>
        <div className={cn("flex items-start", collapsed ? "flex-col items-center gap-2" : "justify-between gap-3")}>
          <div
            className={cn(
              "rounded-[1.3rem] border border-line/70 bg-[linear-gradient(135deg,rgba(31,94,255,0.1),rgba(215,90,45,0.08))] transition-all duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
              collapsed ? "flex h-11 w-11 items-center justify-center rounded-[1.1rem]" : "flex flex-1 items-center gap-3 px-4 py-3.5"
            )}
          >
            <div className={cn("flex items-center justify-center rounded-[1rem] bg-ink text-paper", collapsed ? "h-8 w-8" : "h-9 w-9")}>
              <Sparkles className="h-4 w-4" />
            </div>
            <div className={animatedTextBlock(collapsed, "max-w-[220px]")}>
              <p className="text-[11px] uppercase tracking-[0.22em] text-[#5f6b79]">{translate("shell.brand")}</p>
              <h1 className="mt-1 text-xl font-semibold leading-tight">{translate("shell.title")}</h1>
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
      <nav className={cn("flex flex-1 flex-col", collapsed ? "gap-2.5" : "gap-1.5")}>
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
                  ? "flex h-11 w-11 items-center justify-center self-center rounded-[1rem]"
                  : "rounded-[1.1rem] px-3.5 py-3",
                active
                  ? "scale-[1.02] bg-ink text-paper shadow-[0_16px_32px_rgba(20,32,44,0.18)]"
                  : "text-[#314051] hover:bg-white/70 hover:scale-[1.02]",
                collapsed && active ? "ring-2 ring-[rgba(31,94,255,0.18)] ring-offset-2 ring-offset-card" : null
              )}
            >
              <div className={cn("flex items-center", collapsed ? "justify-center" : "gap-3")}>
                <div
                  className={cn(
                    "flex h-9 w-9 items-center justify-center rounded-[1rem] transition-all duration-300",
                    active ? "bg-white/12" : "bg-[rgba(20,32,44,0.06)]"
                  )}
                >
                  <Icon className="h-4 w-4" />
                </div>
                <div className={animatedTextBlock(collapsed, "max-w-[170px]")}>
                  <div className="text-sm font-medium">{label}</div>
                  <div className={cn("mt-0.5 text-[11px]", active ? "text-white/70" : "text-[#7a8593]")}>{description}</div>
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
      <div className={cn("mt-5", collapsed ? "flex justify-center" : "space-y-3")}>
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
  const { locale, setLocale } = useLocale();
  const { tier, isMobile, isTabletPortrait, isTabletWide, isDesktop } = useResponsiveTier();
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
    if (basePath === "/preview") {
      return;
    }
    if (locale !== sessionUser.language_code) {
      setLocale(sessionUser.language_code);
    }
  }, [basePath, locale, sessionUser.language_code, setLocale]);

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

  const showDesktopSidebar = isDesktop;
  const showTabletSidebar = isTabletWide;
  const showTopBar = !showDesktopSidebar && !showTabletSidebar;
  const tabletStatusStack = isTabletPortrait;

  return (
    <div data-terminal={tier} className="mx-auto flex min-h-screen max-w-[1500px] gap-3 p-3 md:p-4 lg:gap-5 lg:p-5 xl:gap-6 xl:p-6">
      <aside className="hidden shrink-0 lg:flex xl:hidden">
        {showTabletSidebar ? (
          <div className="w-[92px] rounded-[1.35rem] border border-line/80 bg-card p-3 shadow-[var(--shadow-panel)]">
            <NavContentWithItems
              pathname={pathname}
              items={navItems}
              collapsed
              onPrimeRoute={primeRoute}
              logoutRedirectTo={basePath ? withBasePath(basePath, "/") : "/login"}
            />
          </div>
        ) : null}
      </aside>
      <aside
        className={cn(
          "hidden shrink-0 flex-col overflow-visible rounded-[1.45rem] border border-line/80 bg-card p-4 shadow-[var(--shadow-panel)] transition-[width,padding] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] xl:flex",
          desktopNavCollapsed ? "w-[72px] p-3" : "w-[285px]"
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
      <div className="flex min-w-0 flex-1 flex-col gap-5 xl:gap-6">
        <div
          className={cn(
            "items-center justify-between gap-3 rounded-[1.2rem] border border-line/70 bg-card px-4 py-3 shadow-[var(--shadow-panel)]",
            showTopBar ? "flex" : "hidden",
          )}
        >
          <div className="min-w-0">
            <p className="text-[11px] uppercase tracking-[0.22em] text-[#6d7885]">{translate("shell.brand")}</p>
            <p className="mt-1 text-base font-semibold">{translate("shell.title")}</p>
          </div>
          <div className="flex items-center gap-2">
            <LogoutButton redirectTo={basePath ? withBasePath(basePath, "/") : "/login"} />
            <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
              <SheetTrigger asChild>
                <button aria-label={translate("shell.openNavigation")} className="flex h-11 w-11 items-center justify-center rounded-2xl bg-ink text-paper">
                  <Menu className="h-5 w-5" />
                </button>
              </SheetTrigger>
                <SheetContent
                  side="left"
                  className={cn(
                    "nav-panel-content",
                    isTabletPortrait ? "w-[74vw] max-w-[30rem]" : "w-[88vw] max-w-sm",
                  )}
                >
                  <SheetTitle className="sr-only">{translate("shell.openNavigation")}</SheetTitle>
                  <SheetDescription className="sr-only">{translate("shell.navigateDescription")}</SheetDescription>
                  <div className="mb-4 flex items-center justify-end">
                    <SheetDismissButton />
                  </div>
                  <NavContentWithItems
                    pathname={pathname}
                    items={navItems}
                    collapsed={false}
                    onPrimeRoute={primeRoute}
                    logoutRedirectTo={basePath ? withBasePath(basePath, "/") : "/login"}
                  />
                </SheetContent>
            </Sheet>
          </div>
        </div>
        <div
          className={cn(
            "animate-surface-enter rounded-[1.15rem] border border-line/70 bg-card px-4 py-3 shadow-[var(--shadow-panel)]",
            isMobile
              ? "space-y-3"
              : tabletStatusStack
                ? "space-y-3"
                : "flex flex-col gap-2 md:flex-row md:items-center md:justify-between",
          )}
        >
          <p className="text-[11px] uppercase tracking-[0.22em] text-[#6d7885]">{translate("shell.workspaceStatus")}</p>
          <div
            className={cn(
              "text-xs text-[#314051]",
              isMobile ? "grid grid-cols-2 gap-2" : tabletStatusStack ? "flex flex-wrap gap-2" : "flex flex-wrap gap-2",
            )}
          >
            <span className={cn("rounded-full border border-line/80 bg-white/80 px-3 py-1.5", isMobile ? "col-span-2 truncate" : "min-w-0")}>
              {sessionUser.email}
            </span>
            <span className={cn("rounded-full border border-line/80 bg-white/80 px-3 py-1.5", isTabletPortrait || isTabletWide ? "min-w-0" : null)}>
              {sessionUser.timezone_name}
            </span>
            <span className={cn(
              "inline-flex items-center gap-2 rounded-full border px-3 py-1.5",
              isMobile ? "col-span-2 justify-center" : tabletStatusStack ? "w-full justify-center" : null,
              onboardingReady ? "border-[rgba(77,124,15,0.18)] bg-[rgba(77,124,15,0.08)] text-[#3f5f12]" : "border-[rgba(215,90,45,0.18)] bg-[rgba(215,90,45,0.08)] text-[#8a472d]",
            )}>
              <CircleAlert className="h-4 w-4" />
              {onboardingReady ? translate("shell.systemReady") : translate("onboarding.onboardingRequired")}
            </span>
          </div>
        </div>
        <div key={`${basePath}:${pathname}`} className="motion-scene animate-scene-enter min-w-0 flex-1">
          {children}
        </div>
      </div>
    </div>
  );
}
