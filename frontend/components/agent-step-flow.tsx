"use client";

import { ChevronDown } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { workbenchStateSurfaceClassName, workbenchSupportPanelClassName } from "@/lib/workbench-styles";
import { cn } from "@/lib/utils";

type AgentStepState = "active" | "complete" | "terminal";

function stateClassName(state: AgentStepState) {
  switch (state) {
    case "active":
      return workbenchStateSurfaceClassName("info");
    case "terminal":
      return workbenchSupportPanelClassName("quiet");
    default:
      return workbenchSupportPanelClassName("default");
  }
}

export function AgentStepCard({
  eyebrow,
  title,
  summary,
  badge,
  state = "active",
  actions,
  children,
  className,
}: {
  eyebrow: string;
  title: string;
  summary?: string | null;
  badge?: React.ReactNode;
  state?: AgentStepState;
  actions?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("p-4", stateClassName(state), className)}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{eyebrow}</p>
          <h3 className="mt-2 text-base font-semibold text-ink">{title}</h3>
          {summary ? <p className="mt-2 text-sm leading-6 text-[#596270]">{summary}</p> : null}
        </div>
        {badge ? badge : null}
      </div>
      {children ? <div className="mt-4">{children}</div> : null}
      {actions ? <div className="mt-4 flex flex-wrap gap-2">{actions}</div> : null}
    </Card>
  );
}

export function AgentDisclosure({
  title,
  children,
  defaultOpen = false,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details open={defaultOpen || undefined} className={cn("group", workbenchSupportPanelClassName("quiet", "p-3"))}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-medium text-ink">
        <span>{title}</span>
        <ChevronDown className="h-4 w-4 text-[#6d7885] transition-transform group-open:rotate-180" />
      </summary>
      <div className="mt-3">{children}</div>
    </details>
  );
}

export function AgentMobileTriggerCard({
  eyebrow,
  title,
  summary,
  badge,
  action,
}: {
  eyebrow: string;
  title: string;
  summary?: string | null;
  badge?: React.ReactNode;
  action: React.ReactNode;
}) {
  return (
    <AgentStepCard eyebrow={eyebrow} title={title} summary={summary} badge={badge} state="active" actions={action} />
  );
}
