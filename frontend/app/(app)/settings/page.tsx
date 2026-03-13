import { PageHeader } from "@/components/page-header";
import { SettingsPanel } from "@/components/settings-panel";

export default function SettingsPage() {
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Profile" title="Settings" description="Manage timezone and notification identity so review links and account context remain predictable." />
      <SettingsPanel />
    </div>
  );
}
