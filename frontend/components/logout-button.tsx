"use client";

import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { logout } from "@/lib/api/auth";
import { useState } from "react";

export function LogoutButton() {
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
    <Button variant="ghost" className="w-full justify-start rounded-[1.25rem] border border-line/80 bg-white/55 px-4" disabled={submitting} onClick={() => void runLogout()}>
      <LogOut className="mr-2 h-4 w-4" />
      {submitting ? "Signing out..." : "Logout"}
    </Button>
  );
}
