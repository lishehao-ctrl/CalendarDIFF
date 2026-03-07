"use client";

import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { backendFetch } from "@/lib/backend";
import { useState } from "react";

export function LogoutButton() {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);

  async function logout() {
    setSubmitting(true);
    try {
      await backendFetch("/auth/logout", { method: "POST" });
      router.replace("/login");
      router.refresh();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Button variant="ghost" onClick={() => void logout()} disabled={submitting}>
      <LogOut className="mr-2 h-4 w-4" />
      {submitting ? "Signing out..." : "Logout"}
    </Button>
  );
}
