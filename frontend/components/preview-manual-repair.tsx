"use client";

import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Wrench, PlusSquare, PencilRuler } from "lucide-react";
import { getDemoPreviewState } from "@/lib/demo-backend";

export function PreviewManualRepair() {
  const demo = getDemoPreviewState();
  const activeEvents = demo.manualEvents.filter((row) => row.lifecycle === "active");

  return (
    <div className="space-y-5">
      <Card className="relative overflow-hidden p-6 md:p-7">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.1),transparent_36%),radial-gradient(circle_at_82%_20%,rgba(47,143,91,0.12),transparent_22%)]" />
        <div className="relative flex flex-wrap items-start justify-between gap-5">
          <div className="max-w-3xl">
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Manual</p>
            <h1 className="mt-3 text-3xl font-semibold text-ink">Manual is the repair bench, not the main workflow.</h1>
            <p className="mt-3 text-sm leading-7 text-[#596270]">
              The user should arrive here only after deciding that Changes, Families, and Sources cannot safely resolve the situation. The page should explain that clearly.
            </p>
          </div>
          <Badge tone="info">{activeEvents.length} active manual events</Badge>
        </div>
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card className="p-5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[rgba(31,94,255,0.1)] text-cobalt">
              <PlusSquare className="h-4 w-4" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Path 1</p>
              <h2 className="mt-1 text-lg font-semibold text-ink">Add a missing graded item</h2>
            </div>
          </div>
          <p className="mt-4 text-sm leading-6 text-[#596270]">
            Use this when the system never surfaced the event at all. This is not for routine approvals or family cleanup.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Badge tone="approved">Missing event</Badge>
            <Badge tone="info">Canonical repair</Badge>
          </div>
        </Card>

        <Card className="p-5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[rgba(215,90,45,0.12)] text-ember">
              <PencilRuler className="h-4 w-4" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Path 2</p>
              <h2 className="mt-1 text-lg font-semibold text-ink">Correct an existing event</h2>
            </div>
          </div>
          <p className="mt-4 text-sm leading-6 text-[#596270]">
            Use this when the canonical timeline is wrong and the normal review flow cannot safely represent the correction.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Badge tone="pending">Fallback tool</Badge>
            <Badge tone="info">Use sparingly</Badge>
          </div>
        </Card>
      </div>

      <Card className="p-5">
        <div className="flex items-center gap-2">
          <Wrench className="h-4 w-4 text-cobalt" />
          <p className="text-sm font-medium text-ink">When to come here</p>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <div className="rounded-[1rem] border border-line/80 bg-white/72 p-4 text-sm text-[#314051]">
            <p className="font-medium text-ink">1. Try Changes first</p>
            <p className="mt-2 text-[#596270]">If the system already detected the change, make the decision there.</p>
          </div>
          <div className="rounded-[1rem] border border-line/80 bg-white/72 p-4 text-sm text-[#314051]">
            <p className="font-medium text-ink">2. Try Families next</p>
            <p className="mt-2 text-[#596270]">If the problem is naming drift, teach the canonical label there.</p>
          </div>
          <div className="rounded-[1rem] border border-line/80 bg-white/72 p-4 text-sm text-[#314051]">
            <p className="font-medium text-ink">3. Use Manual last</p>
            <p className="mt-2 text-[#596270]">Only use Manual when the system cannot safely cover the edge case.</p>
          </div>
        </div>
      </Card>
    </div>
  );
}
