import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  "motion-button soft-press inline-flex items-center justify-center rounded-full text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[rgba(31,94,255,0.24)] disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "soft-hover bg-cobalt text-white shadow-[0_8px_18px_rgba(31,94,255,0.2)] hover:bg-[#184fd9]",
        secondary: "soft-hover bg-ink text-paper hover:bg-[#27313d]",
        ghost: "soft-hover bg-transparent text-ink hover:bg-[rgba(20,32,44,0.06)]",
        danger: "soft-hover bg-ember text-white hover:bg-[#bf4a20]",
        soft: "soft-hover bg-cobalt-soft text-cobalt shadow-[0_4px_10px_rgba(31,94,255,0.06)] hover:bg-[rgba(31,94,255,0.16)]"
      },
      size: {
        md: "h-11 px-5",
        sm: "h-9 px-4 text-xs",
        lg: "h-12 px-6 text-sm"
      }
    },
    defaultVariants: {
      variant: "primary",
      size: "md"
    }
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export function Button({ className, variant, size, asChild = false, ...props }: ButtonProps) {
  const Component = asChild ? Slot : "button";
  return <Component className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}
