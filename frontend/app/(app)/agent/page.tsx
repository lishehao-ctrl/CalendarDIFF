import { AgentWorkspacePanel } from "@/components/agent-workspace-panel";
import { LocalizedPageIntro } from "@/components/localized-page-intro";
import { requireReadyServerSession } from "@/lib/server-auth";

export default async function AgentPage() {
  await requireReadyServerSession();
  return (
    <div className="space-y-4">
      <LocalizedPageIntro
        eyebrowKey="agentPage.eyebrow"
        titleKey="agentPage.title"
        summaryKey="agentPage.summary"
      />
      <AgentWorkspacePanel />
    </div>
  );
}
