"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { getCurrentUser, updateCurrentUser } from "@/lib/api/users";
import { getBrowserTimeZone } from "@/lib/browser-timezone";
import { useApiResource } from "@/lib/use-api-resource";
import { formatDateTime } from "@/lib/presenters";
import type { UserProfile } from "@/lib/types";

export function SettingsPanel() {
  const user = useApiResource<UserProfile>(() => getCurrentUser(), []);

  const [form, setForm] = useState({ timezone_name: "" });
  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [savingUser, setSavingUser] = useState(false);
  const [deviceTimeZone, setDeviceTimeZone] = useState<string | null>(null);

  useEffect(() => {
    setDeviceTimeZone(getBrowserTimeZone());
  }, []);

  useEffect(() => {
    if (user.data) setForm({ timezone_name: user.data.timezone_name || "" });
  }, [user.data]);

  async function saveUser() {
    setSavingUser(true);
    setBanner(null);
    try {
      await updateCurrentUser({ timezone_name: form.timezone_name, timezone_source: "manual" });
      setBanner({ tone: "info", text: "Settings saved." });
      await user.refresh();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to save settings" });
    } finally {
      setSavingUser(false);
    }
  }

  function applyDeviceTimeZone() {
    if (!deviceTimeZone) return;
    setForm({ timezone_name: deviceTimeZone });
    setBanner(null);
  }

  if (user.loading) return <LoadingState label="settings" />;
  if (user.error) return <ErrorState message={user.error} />;
  if (!user.data) return <EmptyState title="User not initialized" description="Complete registration before editing settings." />;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Account</p>
              <h3 className="mt-2 text-lg font-semibold text-ink">Timezone and identity</h3>
            </div>
            <Badge tone="info">{user.data.timezone_source === "manual" ? "Manual" : "Auto"}</Badge>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
            <div>
              <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="notify-email-settings">Login / notify email</label>
              <Input id="notify-email-settings" value={user.data.notify_email || ""} disabled />
            </div>
            <div>
              <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="timezone-name">Timezone name</label>
              <Input id="timezone-name" value={form.timezone_name} onChange={(event) => setForm({ timezone_name: event.target.value })} placeholder="America/Los_Angeles" />
            </div>
            <Button className="md:min-w-[132px]" onClick={() => void saveUser()} disabled={savingUser || !form.timezone_name}>
              {savingUser ? "Saving..." : "Save"}
            </Button>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-[#596270]">
            <span>Device timezone: {deviceTimeZone || "Unavailable"}</span>
            {deviceTimeZone ? (
              <button type="button" className="font-medium text-cobalt transition hover:text-[#1f4fd6]" onClick={applyDeviceTimeZone}>
                Use device timezone
              </button>
            ) : null}
          </div>
        </Card>

        <Card className="p-4">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Runtime</p>
          <h3 className="mt-2 text-lg font-semibold text-ink">Current defaults</h3>
          <div className="mt-4 flex flex-wrap gap-2 text-sm text-[#314051]">
            <span className="rounded-full border border-line/80 bg-white/70 px-3 py-1.5">{formatDateTime(user.data.created_at, "Not available")}</span>
            <span className="rounded-full border border-line/80 bg-white/70 px-3 py-1.5">{user.data.timezone_name}</span>
            <span className="rounded-full border border-line/80 bg-white/70 px-3 py-1.5">
              {user.data.timezone_source === "manual" ? "Manual override" : "Auto timezone"}
            </span>
            <span className="rounded-full border border-line/80 bg-white/70 px-3 py-1.5">{user.data.calendar_delay_seconds}s delay</span>
          </div>
        </Card>
      </div>

      {banner ? (
        <Card className={banner.tone === "error" ? "border-[#efc4b5] bg-[#fff3ef] p-4" : "border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] p-4"}>
          <p className="text-sm text-[#314051]">{banner.text}</p>
        </Card>
      ) : null}

      <Card className="p-4">
        <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Moved</p>
        <h3 className="mt-2 text-lg font-semibold text-ink">Families now live in Family</h3>
        <p className="mt-2 text-sm text-[#596270]">Canonical labels and raw-type rules now live in the Family module.</p>
        <div className="mt-4">
          <Button asChild size="sm">
            <Link href="/review/links">Open Family</Link>
          </Button>
        </div>
      </Card>
    </div>
  );
}
