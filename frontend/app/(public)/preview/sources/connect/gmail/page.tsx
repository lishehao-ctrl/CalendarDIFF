import dynamic from "next/dynamic";
import { WorkbenchLoadingShell } from "@/components/workbench-loading-shell";

const DeferredGmailSourceSetupPanel = dynamic(
  () => import("@/components/gmail-source-setup-panel").then((mod) => mod.GmailSourceSetupPanel),
  {
    loading: () => <WorkbenchLoadingShell variant="source-connect" />,
  },
);

export default function PreviewGmailPage() {
  return <DeferredGmailSourceSetupPanel basePath="/preview" />;
}
