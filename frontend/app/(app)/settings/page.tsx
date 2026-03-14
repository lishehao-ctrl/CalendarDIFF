import { PageHeader } from "@/components/page-header";
import { SettingsPanel } from "@/components/settings-panel";

export default function SettingsPage() {
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Settings" title="Keep account details predictable" description="Update timezone and notification identity so the review workspace stays consistent across devices." />
      <SettingsPanel />
    </div>
  );
}
