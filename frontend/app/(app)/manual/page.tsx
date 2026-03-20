import { ManualWorkbenchPanel } from "@/components/manual-workbench-panel";
import { requireReadyServerSession } from "@/lib/server-auth";

export default async function ManualPage() {
  await requireReadyServerSession();

  return (
    <div className="space-y-4">
      <div className="px-1">
        <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">Manual</p>
        <h1 className="mt-1 text-2xl font-semibold text-ink">Fallback repairs</h1>
        <p className="mt-2 text-sm text-[#596270]">Use Manual only when the system could not safely express or recover an event.</p>
      </div>
      <ManualWorkbenchPanel />
    </div>
  );
}
