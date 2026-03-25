"use client";

import * as Dialog from "@radix-ui/react-dialog";
import * as React from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export const Sheet = Dialog.Root;
export const SheetTrigger = Dialog.Trigger;
export const SheetClose = Dialog.Close;
export const SheetPortal = Dialog.Portal;

export const SheetOverlay = React.forwardRef<
  React.ElementRef<typeof Dialog.Overlay>,
  React.ComponentPropsWithoutRef<typeof Dialog.Overlay>
>(function SheetOverlay({ className, ...props }, ref) {
  return <Dialog.Overlay ref={ref} className={cn("sheet-overlay fixed inset-0 z-40 bg-[rgba(20,32,44,0.38)] backdrop-blur-sm", className)} {...props} />;
});

export const SheetContent = React.forwardRef<
  React.ElementRef<typeof Dialog.Content>,
  React.ComponentPropsWithoutRef<typeof Dialog.Content> & { side?: "right" | "bottom" }
>(function SheetContent({ className, children, side = "right", ...props }, ref) {
  const sideClassName = side === "bottom"
    ? "sheet-content--bottom motion-surface fixed inset-x-0 bottom-0 z-50 max-h-[85vh] rounded-t-[1.7rem] border-t border-line bg-card p-5 shadow-[var(--shadow-panel)]"
    : "sheet-content--right motion-surface fixed inset-y-0 right-0 z-50 h-full w-full max-w-2xl border-l border-line bg-card p-5 shadow-[var(--shadow-panel)]";
  return (
    <Dialog.Portal>
      <SheetOverlay />
      <Dialog.Content ref={ref} className={cn(sideClassName, className)} {...props}>
        {children}
      </Dialog.Content>
    </Dialog.Portal>
  );
});

export function SheetHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex items-start justify-between gap-4", className)} {...props} />;
}

export const SheetTitle = React.forwardRef<
  React.ElementRef<typeof Dialog.Title>,
  React.ComponentPropsWithoutRef<typeof Dialog.Title>
>(function SheetTitle({ className, ...props }, ref) {
  return <Dialog.Title ref={ref} className={cn("text-2xl font-semibold text-ink", className)} {...props} />;
});

export const SheetDescription = React.forwardRef<
  React.ElementRef<typeof Dialog.Description>,
  React.ComponentPropsWithoutRef<typeof Dialog.Description>
>(function SheetDescription({ className, ...props }, ref) {
  return <Dialog.Description ref={ref} className={cn("mt-2 text-sm leading-6 text-[#596270]", className)} {...props} />;
});

export function SheetDismissButton() {
  return (
    <Dialog.Close asChild>
      <button aria-label="Close details" className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[rgba(20,32,44,0.06)] text-ink">
        <X className="h-4 w-4" />
      </button>
    </Dialog.Close>
  );
}
