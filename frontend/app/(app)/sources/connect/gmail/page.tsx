import { PageHeader } from "@/components/page-header";
import { GmailSourceSetupPanel } from "@/components/gmail-source-setup-panel";

export default function GmailConnectPage() {
  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Sources"
        title="Gmail Setup"
        description="Connect, reconnect, or disconnect the Gmail mailbox attached to this workspace."
      />
      <GmailSourceSetupPanel />
    </div>
  );
}
