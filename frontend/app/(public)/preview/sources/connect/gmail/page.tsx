import dynamic from "next/dynamic";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";

const DeferredGmailSourceSetupPanel = dynamic(
  () => import("@/components/gmail-source-setup-panel").then((mod) => mod.GmailSourceSetupPanel),
  {
    loading: () => <PanelLoadingPlaceholder rows={2} />,
  },
);

export default function PreviewGmailPage() {
  return <DeferredGmailSourceSetupPanel basePath="/preview" />;
}
