"use client";

import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { logout } from "@/lib/api/auth";
import { useState } from "react";
import { cn } from "@/lib/utils";

export function LogoutButton({
  collapsed = false,
  className,
}: {
  collapsed?: boolean;
  className?: string;
} = {}) {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);

  async function runLogout() {
    setSubmitting(true);
    try {
      await logout();
      router.replace("/login");
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
        className
      )}
      aria-label={submitting ? "Signing out" : "Logout"}
      title={submitting ? "Signing out" : "Logout"}
      disabled={submitting}
      onClick={() => void runLogout()}
    >
      <LogOut className={cn("h-4 w-4", collapsed ? "" : "mr-2")} />
      {collapsed ? null : submitting ? "Signing out..." : "Logout"}
    </Button>
  );
}
