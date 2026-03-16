"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const items = [
  { href: "/review/links", label: "Manage Families" },
  { href: "/review/links/add", label: "Add Family" },
] as const;

export function FamilySubnav() {
  const pathname = usePathname();

  return (
    <div className="inline-flex flex-wrap items-center gap-1 rounded-[1rem] border border-line/80 bg-white/72 p-1 shadow-[var(--shadow-panel)]">
      {items.map((item) => {
        const active = pathname === item.href;
        return (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              active
                ? "rounded-[0.95rem] bg-ink px-4 py-2 text-sm font-medium text-paper transition"
                : "rounded-[0.95rem] px-4 py-2 text-sm font-medium text-[#596270] transition hover:bg-white"
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </div>
  );
}
