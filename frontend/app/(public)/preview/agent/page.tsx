import { AgentWorkspacePanel } from "@/components/agent-workspace-panel";
import { LocalizedPageIntro } from "@/components/localized-page-intro";

export default function PreviewAgentPage() {
  return (
    <div className="space-y-4">
      <LocalizedPageIntro
        eyebrowKey="agentPage.eyebrow"
        titleKey="agentPage.title"
        summaryKey="agentPage.summary"
      />
      <AgentWorkspacePanel basePath="/preview" />
    </div>
  );
}
