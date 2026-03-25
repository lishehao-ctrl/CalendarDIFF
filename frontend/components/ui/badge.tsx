import { cn } from "@/lib/utils";
import * as React from "react";

const palette: Record<string, string> = {
  active: "border-[rgba(47,143,91,0.14)] bg-[var(--moss-soft)] text-moss",
  pending: "border-[rgba(215,90,45,0.13)] bg-[#fff1dc] text-ember",
  approved: "border-[rgba(31,94,255,0.13)] bg-[var(--cobalt-soft)] text-cobalt",
  rejected: "border-[rgba(215,90,45,0.13)] bg-[#fbe4dd] text-ember",
  error: "border-[rgba(215,90,45,0.13)] bg-[#fbe4dd] text-ember",
  info: "border-[rgba(20,32,44,0.07)] bg-[rgba(20,32,44,0.05)] text-ink",
  default: "border-[rgba(20,32,44,0.07)] bg-[rgba(20,32,44,0.05)] text-ink"
};

export function Badge({ tone = "default", className, children }: React.PropsWithChildren<{ tone?: string; className?: string }>) {
  return (
    <span
      className={cn(
        "inline-flex min-h-[1.75rem] items-center rounded-full border px-3 py-[0.28rem] text-[10px] font-semibold tracking-[0.08em]",
        palette[tone] || palette.default,
        className,
      )}
    >
      {children}
    </span>
  );
}
