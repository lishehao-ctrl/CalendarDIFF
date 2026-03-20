import { SettingsPanel } from "@/components/settings-panel";

export default function PreviewSettingsPage() {
  return (
    <div className="space-y-4">
      <div className="px-1">
        <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">Settings</p>
        <h1 className="mt-1 text-2xl font-semibold text-ink">Account and timezone</h1>
      </div>
      <SettingsPanel />
    </div>
  );
}
