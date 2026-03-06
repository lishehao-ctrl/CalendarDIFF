import { cn } from "@/lib/utils";
import * as React from "react";

const palette: Record<string, string> = {
  active: "bg-[var(--moss-soft)] text-moss",
  pending: "bg-[#fff1dc] text-ember",
  approved: "bg-[var(--cobalt-soft)] text-cobalt",
  rejected: "bg-[#fbe4dd] text-ember",
  error: "bg-[#fbe4dd] text-ember",
  info: "bg-[rgba(20,32,44,0.08)] text-ink",
  default: "bg-[rgba(20,32,44,0.08)] text-ink"
};

export function Badge({ tone = "default", className, children }: React.PropsWithChildren<{ tone?: string; className?: string }>) {
  return (
    <span className={cn("inline-flex items-center rounded-full px-3 py-1 text-xs font-medium", palette[tone] || palette.default, className)}>
      {children}
    </span>
  );
}
