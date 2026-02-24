import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

import { AppNav, AppNavCurrent, AppNavDensity } from "@/components/dashboard/app-nav";
import { Card } from "@/components/ui/card";

type DashboardPageProps = {
  children: ReactNode;
  maxWidthClassName?: string;
};

type DashboardPageHeaderProps = {
  icon: LucideIcon;
  title: string;
  description: string;
  current: AppNavCurrent;
  activeInputId: number | null;
  showDev?: boolean;
  navDensity?: AppNavDensity;
  actions?: ReactNode;
};

export function DashboardPage({ children, maxWidthClassName = "max-w-6xl" }: DashboardPageProps) {
  return (
    <div className="container py-4 md:py-6">
      <div className={`mx-auto ${maxWidthClassName} space-y-4 md:space-y-6`}>{children}</div>
    </div>
  );
}

export function DashboardPageHeader({
  icon: Icon,
  title,
  description,
  current,
  activeInputId,
  showDev = false,
  navDensity = "comfortable",
  actions,
}: DashboardPageHeaderProps) {
  return (
    <Card className="page-panel animate-in p-5">
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h1 className="inline-flex items-center gap-2 text-2xl font-semibold md:text-3xl">
              <Icon className="h-6 w-6 text-accent" />
              {title}
            </h1>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-muted">{description}</p>
          </div>
          {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
        </div>
        <AppNav current={current} activeInputId={activeInputId} showDev={showDev} density={navDensity} />
      </div>
    </Card>
  );
}
