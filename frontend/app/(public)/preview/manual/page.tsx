import { ManualWorkbenchPanel } from "@/components/manual-workbench-panel";

export default function PreviewManualPage() {
  return (
    <div className="space-y-4">
      <div className="px-1">
        <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">Manual</p>
        <h1 className="mt-1 text-2xl font-semibold text-ink">Fallback events</h1>
      </div>
      <ManualWorkbenchPanel />
    </div>
  );
}
