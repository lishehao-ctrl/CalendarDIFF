import { LocalizedPageIntro } from "@/components/localized-page-intro";
import { SettingsPanel } from "@/components/settings-panel";

export default function PreviewSettingsPage() {
  return (
    <div className="space-y-4">
      <LocalizedPageIntro eyebrowKey="settingsPage.eyebrow" titleKey="settingsPage.title" />
      <SettingsPanel />
    </div>
  );
}
