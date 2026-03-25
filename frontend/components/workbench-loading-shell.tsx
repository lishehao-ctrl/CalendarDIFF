import { Card } from "@/components/ui/card";
import {
  workbenchPanelClassName,
  workbenchSkeletonBlockClassName,
  workbenchSkeletonPanelClassName,
} from "@/lib/workbench-styles";
import { cn } from "@/lib/utils";

type WorkbenchLoadingVariant =
  | "overview"
  | "sources"
  | "source-detail"
  | "source-connect"
  | "changes"
  | "families"
  | "manual"
  | "settings";

function SkeletonLine({ className }: { className?: string }) {
  return <div className={workbenchSkeletonBlockClassName(className)} />;
}

function ShellCard({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Card className={cn(workbenchPanelClassName("secondary", "animate-surface-enter p-5"), className)}>
      <div className="space-y-4">{children}</div>
    </Card>
  );
}

function HeaderBlock() {
  return (
    <div className="animate-header-enter px-1">
      <SkeletonLine className="h-3 w-24" />
      <SkeletonLine className="mt-3 h-10 w-72 max-w-full rounded-2xl" />
      <SkeletonLine className="mt-3 h-4 w-4/5 max-w-[42rem]" />
    </div>
  );
}

function TwoColumnShell() {
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-4">
        <ShellCard>
          <SkeletonLine className="h-3 w-28" />
          <SkeletonLine className="h-8 w-48 rounded-2xl" />
          <SkeletonLine className="h-4 w-3/4" />
          <div className="grid gap-3 md:grid-cols-2">
            <div className={workbenchSkeletonPanelClassName("h-24 rounded-[1.2rem]")} />
            <div className={workbenchSkeletonPanelClassName("h-24 rounded-[1.2rem]")} />
          </div>
        </ShellCard>
      </div>
      <div className="space-y-4">
        <ShellCard className="animate-surface-delay-1">
          <SkeletonLine className="h-3 w-24" />
          <SkeletonLine className="h-7 w-40 rounded-2xl" />
          <SkeletonLine className="h-4 w-11/12" />
          <div className={workbenchSkeletonPanelClassName("h-28 rounded-[1.2rem]")} />
        </ShellCard>
      </div>
    </div>
  );
}

function ThreeColumnWorkbenchShell() {
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(300px,0.64fr)_minmax(0,1.36fr)]">
      <ShellCard className="animate-surface-delay-1">
        <SkeletonLine className="h-3 w-20" />
        <SkeletonLine className="h-8 w-40 rounded-2xl" />
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className={workbenchSkeletonPanelClassName("rounded-[1.1rem] p-4")}>
              <SkeletonLine className="h-3 w-20" />
              <SkeletonLine className="mt-3 h-7 w-32 rounded-2xl" />
              <SkeletonLine className="mt-3 h-4 w-full" />
              <SkeletonLine className="mt-3 h-4 w-3/4" />
            </div>
          ))}
        </div>
      </ShellCard>
      <div className="space-y-5">
        <ShellCard className="animate-surface-delay-2">
          <SkeletonLine className="h-3 w-28" />
          <SkeletonLine className="h-8 w-48 rounded-2xl" />
          <div className="grid gap-3 md:grid-cols-2">
            <div className={workbenchSkeletonPanelClassName("h-24 rounded-[1.2rem]")} />
            <div className={workbenchSkeletonPanelClassName("h-24 rounded-[1.2rem]")} />
          </div>
          <div className={workbenchSkeletonPanelClassName("h-48 rounded-[1.2rem]")} />
        </ShellCard>
        <ShellCard className="animate-surface-delay-3">
          <SkeletonLine className="h-3 w-24" />
          <SkeletonLine className="h-7 w-36 rounded-2xl" />
          <div className={workbenchSkeletonPanelClassName("h-36 rounded-[1.2rem]")} />
        </ShellCard>
      </div>
    </div>
  );
}

function QueueDetailShell() {
  return (
    <div className="grid gap-5 xl:grid-cols-[320px_minmax(0,1fr)_320px]">
      <ShellCard className="animate-surface-delay-1">
        <SkeletonLine className="h-3 w-28" />
        <SkeletonLine className="h-8 w-44 rounded-2xl" />
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className={workbenchSkeletonPanelClassName("h-24 rounded-[1.2rem]")} />
          ))}
        </div>
      </ShellCard>
      <ShellCard className="animate-surface-delay-2">
        <SkeletonLine className="h-3 w-24" />
        <SkeletonLine className="h-8 w-40 rounded-2xl" />
        <div className={workbenchSkeletonPanelClassName("h-32 rounded-[1.2rem]")} />
        <div className={workbenchSkeletonPanelClassName("h-40 rounded-[1.2rem]")} />
      </ShellCard>
      <ShellCard className="animate-surface-delay-3">
        <SkeletonLine className="h-3 w-24" />
        <SkeletonLine className="h-8 w-36 rounded-2xl" />
        <div className={workbenchSkeletonPanelClassName("h-28 rounded-[1.2rem]")} />
      </ShellCard>
    </div>
  );
}

function sourceDetailShell() {
  return (
    <div className="space-y-5">
      <ShellCard className="animate-header-enter">
        <SkeletonLine className="h-3 w-24" />
        <SkeletonLine className="h-10 w-56 rounded-2xl" />
        <SkeletonLine className="h-4 w-4/5" />
        <div className="flex flex-wrap gap-2">
          <SkeletonLine className="h-7 w-20 rounded-full" />
          <SkeletonLine className="h-7 w-24 rounded-full" />
          <SkeletonLine className="h-7 w-28 rounded-full" />
        </div>
      </ShellCard>
      <TwoColumnShell />
    </div>
  );
}

function sourceConnectShell() {
  return (
    <div className="space-y-5">
      <HeaderBlock />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
        <ShellCard className="animate-surface-delay-1">
          <SkeletonLine className="h-3 w-28" />
          <SkeletonLine className="h-8 w-56 rounded-2xl" />
          <div className={workbenchSkeletonPanelClassName("h-32 rounded-[1.2rem]")} />
          <div className={workbenchSkeletonPanelClassName("h-44 rounded-[1.2rem]")} />
          <div className={workbenchSkeletonPanelClassName("h-28 rounded-[1.2rem]")} />
        </ShellCard>
        <ShellCard className="animate-surface-delay-2">
          <SkeletonLine className="h-3 w-24" />
          <SkeletonLine className="h-8 w-40 rounded-2xl" />
          <div className={workbenchSkeletonPanelClassName("h-40 rounded-[1.2rem]")} />
        </ShellCard>
      </div>
    </div>
  );
}

export function WorkbenchLoadingShell({ variant }: { variant: WorkbenchLoadingVariant }) {
  if (variant === "source-detail") {
    return sourceDetailShell();
  }

  if (variant === "source-connect") {
    return sourceConnectShell();
  }

  return (
    <div className="space-y-5">
      <HeaderBlock />
      {variant === "overview" ? (
        <TwoColumnShell />
      ) : variant === "sources" ? (
        <TwoColumnShell />
      ) : variant === "changes" ? (
        <ThreeColumnWorkbenchShell />
      ) : variant === "families" ? (
        <QueueDetailShell />
      ) : variant === "manual" ? (
        <QueueDetailShell />
      ) : variant === "settings" ? (
        <TwoColumnShell />
      ) : (
        <TwoColumnShell />
      )}
    </div>
  );
}
