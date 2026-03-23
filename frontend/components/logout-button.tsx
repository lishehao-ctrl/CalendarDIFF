"use client";

import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { logout } from "@/lib/api/auth";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { withBasePath } from "@/lib/demo-mode";
import { useT } from "@/lib/i18n/use-locale";

export function LogoutButton({
  collapsed = false,
  className,
  redirectTo = "/login",
}: {
  collapsed?: boolean;
  className?: string;
  redirectTo?: string;
} = {}) {
  const router = useRouter();
  const t = useT();
  const [submitting, setSubmitting] = useState(false);

  async function runLogout() {
    setSubmitting(true);
    try {
      await logout();
      router.replace(withBasePath("", redirectTo));
      router.refresh();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Button
      variant="ghost"
      className={cn(
        collapsed
          ? "h-12 w-12 rounded-2xl border border-line/80 bg-white/55 px-0"
          : "w-full justify-start rounded-[1.25rem] border border-line/80 bg-white/55 px-4",
        "transition-all duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
        className
      )}
      aria-label={submitting ? t("shell.logout.ariaBusy") : t("shell.logout.label")}
      title={submitting ? t("shell.logout.ariaBusy") : t("shell.logout.label")}
      disabled={submitting}
      onClick={() => void runLogout()}
    >
      <LogOut className={cn("h-4 w-4 transition-[margin] duration-300", collapsed ? "" : "mr-2")} />
      <span
        className={cn(
          "overflow-hidden whitespace-nowrap transition-[max-width,opacity,transform] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
          collapsed ? "max-w-0 translate-x-2 opacity-0" : "max-w-[120px] translate-x-0 opacity-100"
        )}
      >
        {submitting ? t("shell.logout.signingOut") : t("shell.logout.label")}
      </span>
    </Button>
  );
}
