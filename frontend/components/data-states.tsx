"use client";

import Link from "next/link";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n/use-locale";
import { translateLoadingLabel } from "@/lib/i18n/runtime";
import {
  workbenchEmptyClassName,
  workbenchPanelClassName,
  workbenchSkeletonBlockClassName,
  workbenchSkeletonPanelClassName,
  workbenchStateSurfaceClassName,
  workbenchSupportPanelClassName,
} from "@/lib/workbench-styles";

export function LoadingState({ label }: { label: string }) {
  const t = useT();
  return (
    <Card className={workbenchPanelClassName("secondary", "animate-surface-enter p-6")}>
      <div className="space-y-4">
        <div className={workbenchSkeletonPanelClassName("rounded-[1.15rem] p-4")}>
          <div className={workbenchSkeletonBlockClassName("h-3 w-24")} />
          <div className={workbenchSkeletonBlockClassName("mt-3 h-9 w-2/5 rounded-2xl")} />
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <div className={workbenchSkeletonPanelClassName("h-24 rounded-[1.2rem]")} />
          <div className={workbenchSkeletonPanelClassName("h-24 rounded-[1.2rem]")} />
        </div>
      </div>
      <div className={workbenchStateSurfaceClassName("neutral", "mt-4 px-4 py-3")}>
        <p className="text-sm text-[#596270]">{t("common.labels.loading", { label: translateLoadingLabel(label).toLowerCase() })}</p>
      </div>
    </Card>
  );
}

export function ErrorState({
  message,
  actionLabel,
  actionHref,
}: {
  message: string;
  actionLabel?: string;
  actionHref?: string;
}) {
  const t = useT();
  return (
    <Card className={workbenchStateSurfaceClassName("error", "animate-surface-enter p-6")}>
      <p className="text-xs uppercase tracking-[0.18em] text-ember">{t("common.labels.requestError")}</p>
      <p className="mt-3 text-sm leading-6 text-[#7f3d2a]">{message}</p>
      {actionLabel && actionHref ? (
        <div className="mt-4">
          <Button asChild size="sm" variant="ghost">
            <Link href={actionHref}>{actionLabel}</Link>
          </Button>
        </div>
      ) : null}
    </Card>
  );
}

export function EmptyState({ title, description }: { title: string; description: string }) {
  const t = useT();
  return (
    <Card className={workbenchEmptyClassName("p-8")}>
      <div className={workbenchSupportPanelClassName("quiet", "px-4 py-3")}>
        <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{t("common.labels.workspace")}</p>
        <h3 className="mt-2 text-lg font-semibold text-ink">{title}</h3>
        <p className="mt-2 max-w-xl text-sm leading-6 text-[#596270]">{description}</p>
      </div>
    </Card>
  );
}
