import { LocalizedPageIntro } from "@/components/localized-page-intro";
import { SettingsPanel } from "@/components/settings-panel";
import { requireReadyServerSession } from "@/lib/server-auth";

export default async function SettingsPage() {
  await requireReadyServerSession();
  return (
    <div className="space-y-4">
      <LocalizedPageIntro
        eyebrowKey="settingsPage.eyebrow"
        titleKey="settingsPage.title"
        summaryKey="settingsPage.summary"
      />
      <SettingsPanel />
    </div>
  );
}
