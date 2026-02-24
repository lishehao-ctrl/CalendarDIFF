import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

const Sheet = Dialog.Root;
const SheetTrigger = Dialog.Trigger;
const SheetClose = Dialog.Close;

const SheetPortal = ({ children }: { children: React.ReactNode }) => <Dialog.Portal>{children}</Dialog.Portal>;

const SheetOverlay = React.forwardRef<React.ElementRef<typeof Dialog.Overlay>, React.ComponentPropsWithoutRef<typeof Dialog.Overlay>>(
  ({ className, ...props }, ref) => (
    <Dialog.Overlay
      ref={ref}
      className={cn("fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-sm", className)}
      {...props}
    />
  )
);
SheetOverlay.displayName = Dialog.Overlay.displayName;

const SheetContent = React.forwardRef<React.ElementRef<typeof Dialog.Content>, React.ComponentPropsWithoutRef<typeof Dialog.Content>>(
  ({ className, children, ...props }, ref) => (
    <SheetPortal>
      <SheetOverlay />
      <Dialog.Content
        ref={ref}
        className={cn(
          "fixed inset-y-0 left-0 z-50 w-[86%] max-w-sm border-r border-line bg-surface p-6 shadow-xl focus:outline-none",
          className
        )}
        {...props}
      >
        {children}
        <SheetClose className="absolute right-4 top-4 rounded-lg p-1 text-muted hover:bg-slate-100 hover:text-ink">
          <X className="h-5 w-5" />
          <span className="sr-only">Close</span>
        </SheetClose>
      </Dialog.Content>
    </SheetPortal>
  )
);
SheetContent.displayName = Dialog.Content.displayName;

export { Sheet, SheetContent, SheetOverlay, SheetPortal, SheetTrigger };
