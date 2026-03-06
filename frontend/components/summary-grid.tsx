import { ArrowUpRight } from "lucide-react";
import { Card } from "@/components/ui/card";

export function SummaryGrid({ items }: { items: Array<{ label: string; value: string; detail?: string }> }) {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {items.map((item, index) => (
        <Card key={item.label} className="relative overflow-hidden p-5">
          <div className="absolute inset-x-0 top-0 h-1 bg-[linear-gradient(90deg,var(--cobalt),var(--ember))] opacity-70" />
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">{item.label}</p>
              <p className="mt-3 text-3xl font-semibold text-ink">{item.value}</p>
              <p className="mt-2 text-sm text-[#596270]">{item.detail || "Operational snapshot"}</p>
            </div>
            <div className="rounded-2xl bg-[rgba(20,32,44,0.06)] p-3 text-[#6d7885]">
              <ArrowUpRight className="h-4 w-4" />
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}
