"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { getDemoPreviewState } from "@/lib/demo-backend";
import { formatDateTime } from "@/lib/presenters";

export function PreviewSettingsFocus() {
  const demo = getDemoPreviewState();
  const [timezoneName, setTimezoneName] = useState(demo.user.timezone_name);

  return (
    <div className="space-y-5">
      <Card className="relative overflow-hidden p-6 md:p-7">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.08),transparent_36%),radial-gradient(circle_at_82%_18%,rgba(215,90,45,0.08),transparent_20%)]" />
        <div className="relative flex flex-wrap items-start justify-between gap-5">
          <div className="max-w-3xl">
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Settings</p>
            <h1 className="mt-3 text-3xl font-semibold text-ink">Keep this page small and boring.</h1>
            <p className="mt-3 text-sm leading-7 text-[#596270]">
              Settings should not carry migration hints or governance concepts. It should be a thin place for account and timezone preferences, nothing more.
            </p>
          </div>
          <Badge tone="info">Thin lane</Badge>
        </div>
      </Card>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Account</p>
              <h2 className="mt-1 text-lg font-semibold text-ink">Timezone and notify identity</h2>
            </div>
            <Badge tone="info">{demo.user.timezone_source === "manual" ? "Manual" : "Auto"}</Badge>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
            <div>
              <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="preview-notify-email">
                Login / notify email
              </label>
              <Input id="preview-notify-email" value={demo.user.notify_email || ""} disabled />
            </div>
            <div>
              <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="preview-timezone">
                Timezone name
              </label>
              <Input id="preview-timezone" value={timezoneName} onChange={(event) => setTimezoneName(event.target.value)} />
            </div>
            <Button>Save</Button>
          </div>
        </Card>

        <Card className="p-5">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Runtime</p>
          <h2 className="mt-1 text-lg font-semibold text-ink">Current defaults</h2>
          <div className="mt-4 flex flex-wrap gap-2 text-sm text-[#314051]">
            <span className="rounded-full border border-line/80 bg-white/70 px-3 py-1.5">{formatDateTime(demo.user.created_at, "Not available")}</span>
            <span className="rounded-full border border-line/80 bg-white/70 px-3 py-1.5">{demo.user.timezone_name}</span>
            <span className="rounded-full border border-line/80 bg-white/70 px-3 py-1.5">{demo.user.calendar_delay_seconds}s delay</span>
          </div>
        </Card>
      </div>
    </div>
  );
}
