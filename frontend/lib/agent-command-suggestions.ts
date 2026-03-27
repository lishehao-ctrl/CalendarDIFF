import { translate } from "@/lib/i18n/runtime";
import { summarizeChange } from "@/lib/presenters";
import type { AgentBlockingCondition, AgentWorkspaceContext, ChangeItem } from "@/lib/types";

export type AgentCommandSuggestion = {
  id: string;
  label: string;
  prompt: string;
  description?: string;
  source: "static" | "dynamic";
};

function dedupeSuggestions(items: AgentCommandSuggestion[]) {
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = `${item.label}::${item.prompt}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

export function buildStaticAgentCommandSuggestions(): AgentCommandSuggestion[] {
  return [
    {
      id: "review-workspace",
      label: translate("agent.command.exampleSuggestionLabels.reviewWorkspace"),
      prompt: translate("agent.command.examplePrompts.reviewWorkspace"),
      description: translate("agent.command.exampleSuggestionDescriptions.reviewWorkspace"),
      source: "static",
    },
    {
      id: "review-pending-change",
      label: translate("agent.command.exampleSuggestionLabels.reviewPendingChange"),
      prompt: translate("agent.command.examplePrompts.reviewPendingChange"),
      description: translate("agent.command.exampleSuggestionDescriptions.reviewPendingChange"),
      source: "static",
    },
    {
      id: "inspect-source-blockers",
      label: translate("agent.command.exampleSuggestionLabels.inspectSourceBlockers"),
      prompt: translate("agent.command.examplePrompts.inspectSourceBlockers"),
      description: translate("agent.command.exampleSuggestionDescriptions.inspectSourceBlockers"),
      source: "static",
    },
    {
      id: "show-recent-activity",
      label: translate("agent.command.exampleSuggestionLabels.showRecentActivity"),
      prompt: translate("agent.command.examplePrompts.showRecentActivity"),
      description: translate("agent.command.exampleSuggestionDescriptions.showRecentActivity"),
      source: "static",
    },
  ];
}

export function buildRecommendedActionPrompt(context: AgentWorkspaceContext) {
  return translate("agent.command.dynamicPrompts.recommendedActionPrompt", {
    lane: context.recommended_next_action.label,
    reason: context.recommended_next_action.reason,
  });
}

export function buildSourceBlockerPrompt(blockers: AgentBlockingCondition[]) {
  const blocker = blockers.find((item) => item.code.includes("source"));
  return translate("agent.command.dynamicPrompts.sourceBlockerPrompt", {
    blocker: blocker?.message || translate("agent.command.dynamicPrompts.sourceBlockerFallback"),
  });
}

export function buildPendingChangePrompt(change: ChangeItem) {
  const summary = summarizeChange(change);
  return translate("agent.command.dynamicPrompts.pendingChangePrompt", {
    id: String(change.id),
    title: summary.title,
  });
}

export function buildContextualAgentCommandSuggestions(context: AgentWorkspaceContext): AgentCommandSuggestion[] {
  const items: AgentCommandSuggestion[] = [
    {
      id: "recommended-action",
      label: translate("agent.command.dynamicPrompts.recommendedActionLabel", {
        lane: context.recommended_next_action.label,
      }),
      prompt: buildRecommendedActionPrompt(context),
      description: context.recommended_next_action.reason,
      source: "dynamic",
    },
  ];

  const sourceBlocker = context.blocking_conditions.find((item) => item.code.includes("source")) || null;
  if (sourceBlocker) {
    items.push({
      id: "source-blockers",
      label: translate("agent.command.dynamicPrompts.sourceBlockerLabel"),
      prompt: buildSourceBlockerPrompt(context.blocking_conditions),
      description: sourceBlocker.message,
      source: "dynamic",
    });
  }

  const topChange = context.top_pending_changes[0];
  if (topChange) {
    const summary = summarizeChange(topChange);
    items.push({
      id: `top-change-${topChange.id}`,
      label: translate("agent.command.dynamicPrompts.pendingChangeLabel", {
        id: String(topChange.id),
      }),
      prompt: buildPendingChangePrompt(topChange),
      description: translate("agent.command.dynamicPrompts.pendingChangeDescription", {
        title: summary.title,
      }),
      source: "dynamic",
    });
  }

  return dedupeSuggestions(items);
}
