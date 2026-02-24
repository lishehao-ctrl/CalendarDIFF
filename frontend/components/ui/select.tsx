import * as React from "react";

import { cn } from "@/lib/utils";

const Select = React.forwardRef<HTMLSelectElement, React.ComponentProps<"select">>(({ className, ...props }, ref) => {
  return (
    <select
      ref={ref}
      className={cn(
        "focus-ring-soft flex h-10 w-full rounded-xl border border-line bg-white px-3 py-2 text-sm text-ink transition-colors duration-180 hover:border-lineStrong disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  );
});
Select.displayName = "Select";

export { Select };
