import { cn } from "@/lib/utils";
import * as React from "react";

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-[1.4rem] border border-line/80 bg-card backdrop-blur-sm shadow-[var(--shadow-panel)] transition-[transform,box-shadow,border-color,background-color] duration-300",
        className
      )}
      {...props}
    />
  );
}
