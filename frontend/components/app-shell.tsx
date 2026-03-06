"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import * as Dialog from "@radix-ui/react-dialog";
import {
  BellDot,
  GitCompareArrows,
  LayoutDashboard,
  Link2,
  Menu,
  Settings2,
  Sparkles,
  X
} from "lucide-react";
import { cn } from "@/lib/utils";

const items = [
  { href: "/", label: "Overview", icon: LayoutDashboard, description: "Health, onboarding, queue pressure" },
  { href: "/sources", label: "Sources", icon: BellDot, description: "Feeds, sync controls, source health" },
  { href: "/review/changes", label: "Review Inbox", icon: GitCompareArrows, description: "Canonical change moderation" },
  { href: "/review/links", label: "Link Review", icon: Link2, description: "Candidates, links, alerts" },
  { href: "/settings", label: "Settings", icon: Settings2, description: "Timezone and notifications" }
] as const;

function NavContent({ pathname }: { pathname: string }) {
  return (
    <>
      <div className="mb-8 rounded-[1.6rem] bg-[linear-gradient(135deg,rgba(31,94,255,0.18),rgba(215,90,45,0.12))] p-5">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-ink text-paper">
            <Sparkles className="h-5 w-5" />
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.24em] text-[#425061]">CalendarDIFF</p>
            <h1 className="mt-1 text-2xl font-semibold">Editorial Ops Console</h1>
          </div>
        </div>
        <p className="mt-4 text-sm leading-6 text-[#314051]">
          A modern control room for source intake, review operations, link governance, and deadline confidence.
        </p>
      </div>
      <nav className="flex flex-1 flex-col gap-2">
        {items.map(({ href, label, icon: Icon, description }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "rounded-[1.25rem] px-4 py-4 transition",
                active ? "bg-ink text-paper shadow-[0_16px_32px_rgba(20,32,44,0.18)]" : "text-[#314051] hover:bg-white/70"
              )}
            >
              <div className="flex items-center gap-3">
                <div className={cn("flex h-10 w-10 items-center justify-center rounded-2xl", active ? "bg-white/12" : "bg-[rgba(20,32,44,0.06)]") }>
                  <Icon className="h-4 w-4" />
                </div>
                <div>
                  <div className="text-sm font-medium">{label}</div>
                  <div className={cn("mt-1 text-xs", active ? "text-white/70" : "text-[#7a8593]")}>{description}</div>
                </div>
              </div>
            </Link>
          );
        })}
      </nav>
      <div className="mt-6 rounded-[1.25rem] border border-line/80 bg-white/55 p-4 text-sm text-[#596270]">
        Gmail auth remains intentionally blocked in the UI MVP. ICS and review workflows stay fully operational.
      </div>
    </>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="mx-auto flex min-h-screen max-w-[1500px] gap-6 p-4 md:p-6">
      <aside className="hidden w-80 shrink-0 flex-col rounded-[1.7rem] border border-line/80 bg-card p-5 shadow-[var(--shadow-panel)] xl:flex">
        <NavContent pathname={pathname} />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col gap-6">
        <div className="flex items-center justify-between rounded-[1.45rem] border border-line/70 bg-card px-4 py-3 shadow-[var(--shadow-panel)] xl:hidden">
          <div>
            <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">CalendarDIFF</p>
            <p className="mt-1 text-lg font-semibold">Ops Console</p>
          </div>
          <Dialog.Root>
            <Dialog.Trigger asChild>
              <button aria-label="Open navigation" className="flex h-11 w-11 items-center justify-center rounded-2xl bg-ink text-paper">
                <Menu className="h-5 w-5" />
              </button>
            </Dialog.Trigger>
            <Dialog.Portal>
              <Dialog.Overlay className="fixed inset-0 z-40 bg-[rgba(20,32,44,0.38)] backdrop-blur-sm" />
              <Dialog.Content className="fixed inset-y-0 left-0 z-50 w-[88vw] max-w-sm border-r border-line bg-card p-5 shadow-[var(--shadow-panel)]">
                <Dialog.Title className="sr-only">Navigation menu</Dialog.Title>
                <Dialog.Description className="sr-only">Navigate between overview, sources, review, link review, and settings pages.</Dialog.Description>
                <div className="mb-4 flex items-center justify-end">
                  <Dialog.Close asChild>
                    <button aria-label="Close navigation" className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[rgba(20,32,44,0.06)] text-ink">
                      <X className="h-4 w-4" />
                    </button>
                  </Dialog.Close>
                </div>
                <NavContent pathname={pathname} />
              </Dialog.Content>
            </Dialog.Portal>
          </Dialog.Root>
        </div>
        {children}
      </div>
    </div>
  );
}
