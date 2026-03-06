"use client";

import { useEffect, useState } from "react";
import { Clock3, Mail, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { backendFetch } from "@/lib/backend";
import { formatDateTime } from "@/lib/presenters";
import type { UserProfile } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

type Banner = {
  tone: "info" | "error";
  text: string;
} | null;

export function SettingsPanel() {
  const { data, loading, error, refresh } = useResource<UserProfile>("/users/me");
  const [form, setForm] = useState({ notify_email: "", timezone_name: "UTC" });
  const [saving, setSaving] = useState(false);
  const [banner, setBanner] = useState<Banner>(null);

  useEffect(() => {
    if (data) {
      setForm({
        notify_email: data.notify_email || "",
        timezone_name: data.timezone_name || "UTC"
      });
    }
  }, [data]);

  async function save() {
    setSaving(true);
    setBanner(null);
    try {
      await backendFetch<UserProfile>("/users/me", {
        method: "PATCH",
        body: JSON.stringify(form)
      });
      setBanner({ tone: "info", text: "Workspace settings saved." });
      await refresh();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to save settings" });
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <LoadingState label="settings" />;
  if (error) return <ErrorState message={error} />;
  if (!data) return <EmptyState title="User not initialized" description="Complete onboarding before editing settings." />;

  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_0.85fr]">
      <Card className="p-6 md:p-7">
        <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Editable settings</p>
        <h3 className="mt-3 text-2xl font-semibold">Workspace identity</h3>
        <p className="mt-2 text-sm leading-6 text-[#596270]">
          Keep reviewer routing and digest timing predictable by maintaining the notification address and timezone used by the backend.
        </p>

        {banner ? (
          <div className={banner.tone === "error" ? "mt-5 rounded-[1.15rem] border border-[#efc4b5] bg-[#fff3ef] px-4 py-3 text-sm text-[#7f3d2a]" : "mt-5 rounded-[1.15rem] border border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] px-4 py-3 text-sm text-[#314051]"}>
            {banner.text}
          </div>
        ) : null}

        <div className="mt-6 space-y-4">
          <div>
            <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="notify-email-settings">
              Notify email
            </label>
            <Input id="notify-email-settings" value={form.notify_email} onChange={(event) => setForm((prev) => ({ ...prev, notify_email: event.target.value }))} placeholder="notify@example.com" />
          </div>
          <div>
            <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="timezone-name">
              Timezone name
            </label>
            <Input id="timezone-name" value={form.timezone_name} onChange={(event) => setForm((prev) => ({ ...prev, timezone_name: event.target.value }))} placeholder="America/Los_Angeles" />
          </div>
          <Button onClick={() => void save()} disabled={saving || !form.notify_email || !form.timezone_name}>
            {saving ? "Saving settings..." : "Save settings"}
          </Button>
        </div>
      </Card>

      <div className="space-y-5">
        <Card className="p-6">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(31,94,255,0.1)] text-cobalt">
              <Mail className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Identity snapshot</p>
              <h3 className="mt-1 text-xl font-semibold">Current profile</h3>
            </div>
          </div>
          <div className="mt-5 space-y-3 text-sm text-[#314051]">
            <div className="rounded-[1.15rem] border border-line/80 bg-white/60 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Primary email</p>
              <p className="mt-2 font-medium">{data.email || "Not set"}</p>
            </div>
            <div className="rounded-[1.15rem] border border-line/80 bg-white/60 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Notify email</p>
              <p className="mt-2 font-medium">{data.notify_email || "Not set"}</p>
            </div>
            <div className="rounded-[1.15rem] border border-line/80 bg-white/60 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Created</p>
              <p className="mt-2 font-medium">{formatDateTime(data.created_at, "Not available")}</p>
            </div>
          </div>
        </Card>

        <Card className="p-6">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(47,143,91,0.12)] text-moss">
              <Clock3 className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Timing defaults</p>
              <h3 className="mt-1 text-xl font-semibold">Operational timing</h3>
            </div>
          </div>
          <div className="mt-5 rounded-[1.15rem] border border-line/80 bg-white/60 p-4 text-sm text-[#314051]">
            <p>Timezone: {data.timezone_name}</p>
            <p className="mt-2">Calendar delay seconds: {data.calendar_delay_seconds}</p>
          </div>
          <div className="mt-4 rounded-[1.15rem] border border-line/80 bg-white/60 p-4 text-sm text-[#596270]">
            Digest routing and review scheduling continue to rely on backend policy. This screen intentionally edits only the stable user-facing fields first.
          </div>
        </Card>

        <Card className="p-6">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(20,32,44,0.08)] text-ink">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Scope boundary</p>
              <h3 className="mt-1 text-xl font-semibold">What stays out of MVP</h3>
            </div>
          </div>
          <p className="mt-4 text-sm leading-6 text-[#596270]">
            Gmail OAuth, callback routing, and internal ops controls remain backend concerns for now. The frontend keeps the user profile clean and predictable without exposing secrets or internal service actions.
          </p>
        </Card>
      </div>
    </div>
  );
}
