import dynamic from "next/dynamic";
import { LocalizedPageHeader } from "@/components/localized-page-header";
import { WorkbenchLoadingShell } from "@/components/workbench-loading-shell";
import { requireReadyServerSession } from "@/lib/server-auth";

const DeferredGmailSourceSetupPanel = dynamic(
  () => import("@/components/gmail-source-setup-panel").then((mod) => mod.GmailSourceSetupPanel),
  {
    loading: () => <WorkbenchLoadingShell variant="source-connect" />,
  },
);

export default async function GmailConnectPage() {
  await requireReadyServerSession();

  return (
    <div className="space-y-5">
      <LocalizedPageHeader
        eyebrowKey="pageHeader.sources"
        titleKey="sourceConnect.gmailTitle"
        descriptionKey="sourceConnect.gmailSummary"
      />
      <DeferredGmailSourceSetupPanel />
    </div>
  );
}
