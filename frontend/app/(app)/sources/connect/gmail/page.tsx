import { PageHeader } from "@/components/page-header";
import { GmailSourceSetupPanel } from "@/components/gmail-source-setup-panel";
import { requireReadyServerSession } from "@/lib/server-auth";

export default async function GmailConnectPage() {
  await requireReadyServerSession();

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Sources"
        title="Gmail mailbox"
        description="Connect the mailbox, inspect bootstrap vs replay posture, and keep replay intake trustworthy."
      />
      <GmailSourceSetupPanel />
    </div>
  );
}
