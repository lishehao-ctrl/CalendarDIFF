import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-full text-sm font-medium transition-all duration-200 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "bg-cobalt text-white shadow-[0_10px_22px_rgba(31,94,255,0.24)] hover:-translate-y-0.5 hover:bg-[#184fd9]",
        secondary: "bg-ink text-paper hover:-translate-y-0.5 hover:bg-[#27313d]",
        ghost: "bg-transparent text-ink hover:bg-[rgba(20,32,44,0.06)]",
        danger: "bg-ember text-white hover:-translate-y-0.5 hover:bg-[#bf4a20]",
        soft: "bg-cobalt-soft text-cobalt hover:bg-[rgba(31,94,255,0.16)]"
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
    VariantProps<typeof buttonVariants> {}

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return <button className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}
