import { LocalizedPageHeader } from "@/components/localized-page-header";
import { GmailSourceSetupPanel } from "@/components/gmail-source-setup-panel";
import { requireReadyServerSession } from "@/lib/server-auth";

export default async function GmailConnectPage() {
  await requireReadyServerSession();

  return (
    <div className="space-y-5">
      <LocalizedPageHeader
        eyebrowKey="pageHeader.sources"
        titleKey="sourceConnect.gmailTitle"
        descriptionKey="sourceConnect.gmailSummary"
      />
      <GmailSourceSetupPanel />
    </div>
  );
}
