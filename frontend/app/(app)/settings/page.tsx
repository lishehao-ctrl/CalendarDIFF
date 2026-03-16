import { SettingsPanel } from "@/components/settings-panel";
import { requireReadyServerSession } from "@/lib/server-auth";

export default async function SettingsPage() {
  await requireReadyServerSession();
  return (
    <div className="space-y-4">
      <div className="px-1">
        <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">Settings</p>
        <h1 className="mt-1 text-2xl font-semibold text-ink">Workspace settings</h1>
      </div>
      <SettingsPanel />
    </div>
  );
}
