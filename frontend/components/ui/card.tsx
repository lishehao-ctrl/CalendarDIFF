import { cn } from "@/lib/utils";
import * as React from "react";

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-[1.4rem] border border-line/80 bg-card backdrop-blur-sm shadow-[var(--shadow-panel)]",
        className
      )}
      {...props}
    />
  );
}
