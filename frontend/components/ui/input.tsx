import * as React from "react";

import { cn } from "@/lib/utils";

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(({ className, ...props }, ref) => {
  return (
    <input
      ref={ref}
      className={cn(
        "focus-ring-soft flex h-10 w-full rounded-xl border border-line bg-white px-3 py-2 text-sm text-ink transition-colors duration-180 placeholder:text-slate-400 hover:border-lineStrong disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  );
});
Input.displayName = "Input";

export { Input };
