import type { AgentWorkspaceContext } from "@/lib/types";

export function agentLaneHref(lane: AgentWorkspaceContext["recommended_next_action"]["lane"]) {
  return {
    sources: "/sources",
    initial_review: "/changes?bucket=initial_review",
    changes: "/changes",
    families: "/families",
    manual: "/manual",
  }[lane];
}
