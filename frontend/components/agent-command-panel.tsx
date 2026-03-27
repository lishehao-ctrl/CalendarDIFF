"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, Sparkles } from "lucide-react";
import {
  cancelApprovalTicket,
  confirmApprovalTicket,
  createApprovalTicket,
  executeWorkspaceCommand,
  getAgentProposal,
  getApprovalTicket,
  planWorkspaceCommand,
} from "@/lib/api/agents";
import type { AgentCommandSuggestion } from "@/lib/agent-command-suggestions";
import {
  commandBoundaryLabel,
  commandRunStatusLabel,
  commandScopeLabel,
  commandStepStatusLabel,
  commandTargetKindLabel,
  commandToolLabel,
  runGuidanceCopy,
  stepIndexLookup,
  summarizeOutputSummary,
  summarizeStepArgs,
  summarizeStepDependencies,
} from "@/lib/agent-command-presenters";
import { ApprovalTicketBar } from "@/components/approval-ticket-bar";
import { AgentDisclosure } from "@/components/agent-step-flow";
import { AgentProposalCard } from "@/components/agent-proposal-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { translate } from "@/lib/i18n/runtime";
import { formatDateTime, formatStatusLabel } from "@/lib/presenters";
import type { AgentCommandExecutionResult, AgentCommandRun, AgentProposal, ApprovalTicket } from "@/lib/types";
import { workbenchSupportPanelClassName, workbenchStateSurfaceClassName } from "@/lib/workbench-styles";
import { cn } from "@/lib/utils";

const EMPTY_STEPS: AgentCommandRun["plan"] = [];
const EMPTY_SUGGESTIONS: AgentCommandSuggestion[] = [];

function statusTone(status: string) {
  switch (status) {
    case "completed":
    case "succeeded":
      return "approved";
    case "blocked":
    case "failed":
    case "unsupported":
      return "error";
    case "clarification_required":
    case "executing":
      return "pending";
    default:
      return "info";
  }
}

function riskTone(risk: string) {
  switch (risk) {
    case "low":
      return "approved";
    case "high":
      return "error";
    default:
      return "pending";
  }
}

function stepResultFor(run: AgentCommandRun | null, stepId: string): AgentCommandExecutionResult | null {
  if (!run) {
    return null;
  }
  return run.execution_results.find((row) => row.step_id === stepId) || null;
}

function SuggestionCard({
  suggestion,
  onClick,
  testId,
  tone = "default",
}: {
  suggestion: AgentCommandSuggestion;
  onClick: () => void;
  testId: string;
  tone?: "default" | "info";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        workbenchSupportPanelClassName(tone === "info" ? "info" : "quiet", "interactive-lift w-full p-4 text-left"),
        "group",
      )}
      data-testid={testId}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-ink">{suggestion.label}</p>
          {suggestion.description ? (
            <p className="mt-2 text-sm leading-6 text-[#596270]">{suggestion.description}</p>
          ) : null}
        </div>
        <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-[#6d7885] transition-transform duration-200 group-hover:translate-x-0.5" />
      </div>
    </button>
  );
}

function CommandEmptyPanel({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className={workbenchSupportPanelClassName("quiet", "p-4")}>
      <p className="text-sm font-medium text-ink">{title}</p>
      <p className="mt-2 text-sm leading-6 text-[#596270]">{description}</p>
    </div>
  );
}

function isProposalTool(toolName: string) {
  return toolName.startsWith("create_") && toolName.endsWith("_proposal");
}

function isTicketCreationTool(toolName: string) {
  return toolName === "create_approval_ticket";
}

function collectExecutionStepIds(steps: AgentCommandRun["plan"], targetStepId: string) {
  const byId = new Map(steps.map((step) => [step.step_id, step]));
  const required = new Set<string>();

  function visit(stepId: string) {
    if (required.has(stepId)) {
      return;
    }
    const step = byId.get(stepId);
    if (!step) {
      return;
    }
    for (const dep of step.depends_on) {
      visit(dep);
    }
    required.add(stepId);
  }

  visit(targetStepId);
  return steps.filter((step) => required.has(step.step_id)).map((step) => step.step_id);
}

function deriveProposalExecutionIds(steps: AgentCommandRun["plan"]) {
  const proposalStep = steps.find((step) => isProposalTool(step.tool_name));
  if (!proposalStep) {
    return null;
  }
  return collectExecutionStepIds(steps, proposalStep.step_id);
}

function deriveAnalysisExecutionIds(steps: AgentCommandRun["plan"]) {
  const hasProposalStep = steps.some((step) => isProposalTool(step.tool_name));
  const hasTicketCreationStep = steps.some((step) => isTicketCreationTool(step.tool_name));
  if (hasProposalStep || hasTicketCreationStep || steps.length === 0) {
    return null;
  }
  return steps.map((step) => step.step_id);
}

function latestOutputNumber(run: AgentCommandRun | null, key: string) {
  if (!run) {
    return null;
  }
  for (const result of [...run.execution_results].reverse()) {
    const value = result.output_summary?.[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
  }
  return null;
}

function latestOutputString(run: AgentCommandRun | null, key: string) {
  if (!run) {
    return null;
  }
  for (const result of [...run.execution_results].reverse()) {
    const value = result.output_summary?.[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
}

function proposalWebOnlyHref(proposal: AgentProposal, basePath: string) {
  const normalizedBase = basePath ? basePath.replace(/\/$/, "") : "";
  if (proposal.target_kind === "change") {
    return `${normalizedBase}/changes?focus=${proposal.target_id}`;
  }
  if (proposal.target_kind === "source") {
    return `${normalizedBase}/sources/${proposal.target_id}`;
  }
  if (proposal.target_kind === "family") {
    return `${normalizedBase}/families`;
  }
  return normalizedBase ? `${normalizedBase}/agent` : "/agent";
}

type AgentCommandPanelProps = {
  draft: string;
  onDraftChange: (nextValue: string) => void;
  suggestions?: AgentCommandSuggestion[];
  focusRequestToken?: number;
  onRunUpdated?: (run: AgentCommandRun) => void;
  basePath?: string;
};

export function AgentCommandPanel({
  draft,
  onDraftChange,
  suggestions = EMPTY_SUGGESTIONS,
  focusRequestToken = 0,
  onRunUpdated,
  basePath = "",
}: AgentCommandPanelProps) {
  const [run, setRun] = useState<AgentCommandRun | null>(null);
  const [busy, setBusy] = useState<"proposal" | "analysis" | null>(null);
  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [proposal, setProposal] = useState<AgentProposal | null>(null);
  const [ticket, setTicket] = useState<ApprovalTicket | null>(null);
  const [ticketBusy, setTicketBusy] = useState<"create" | "confirm" | "cancel" | "refresh" | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

  const plannedSteps = useMemo(() => run?.plan || EMPTY_STEPS, [run]);
  const stepIndexes = useMemo(() => stepIndexLookup(plannedSteps), [plannedSteps]);
  const displayResults = useMemo(
    () => (run?.execution_results || []).filter((row) => row.status !== "pending"),
    [run],
  );
  const staticSuggestions = useMemo(
    () => suggestions.filter((item) => item.source === "static"),
    [suggestions],
  );
  const dynamicSuggestions = useMemo(
    () => suggestions.filter((item) => item.source === "dynamic"),
    [suggestions],
  );
  const guidance = run ? runGuidanceCopy(run.status) : null;
  const proposalExecutionIds = useMemo(() => deriveProposalExecutionIds(plannedSteps), [plannedSteps]);
  const analysisExecutionIds = useMemo(() => deriveAnalysisExecutionIds(plannedSteps), [plannedSteps]);
  const latestProposalId = useMemo(() => latestOutputNumber(run, "proposal_id"), [run]);
  const latestTicketId = useMemo(() => latestOutputString(run, "ticket_id"), [run]);
  const canClear = Boolean(run || draft.trim() || banner || proposal || ticket);

  useEffect(() => {
    if (!focusRequestToken) {
      return;
    }
    composerRef.current?.focus();
    composerRef.current?.scrollIntoView({ block: "nearest" });
  }, [focusRequestToken]);

  useEffect(() => {
    let cancelled = false;

    async function hydrateArtifacts() {
      try {
        const [nextProposal, nextTicket] = await Promise.all([
          latestProposalId ? getAgentProposal(latestProposalId) : Promise.resolve(null),
          latestTicketId ? getApprovalTicket(latestTicketId) : Promise.resolve(null),
        ]);
        if (cancelled) {
          return;
        }
        if (nextProposal) {
          setProposal(nextProposal);
        }
        if (nextTicket) {
          setTicket(nextTicket);
        }
      } catch {
        // Keep the simplified assistant resilient even if artifact hydration fails.
      }
    }

    if (latestProposalId || latestTicketId) {
      void hydrateArtifacts();
    }
    return () => {
      cancelled = true;
    };
  }, [latestProposalId, latestTicketId]);

  function focusComposer() {
    composerRef.current?.focus();
    composerRef.current?.scrollIntoView({ block: "nearest" });
  }

  function setRunState(nextRun: AgentCommandRun) {
    setRun(nextRun);
    onRunUpdated?.(nextRun);
  }

  function handleFillPrompt(prompt: string) {
    onDraftChange(prompt);
    setBanner(null);
    focusComposer();
  }

  function handleClearCurrentRun() {
    setRun(null);
    setProposal(null);
    setTicket(null);
    setBanner(null);
    onDraftChange("");
    focusComposer();
  }

  function handleComposerKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && draft.trim() && busy !== "proposal") {
      event.preventDefault();
      void handleGenerateProposal();
    }
  }

  async function handleGenerateProposal() {
    setBusy("proposal");
    setBanner(null);
    setProposal(null);
    setTicket(null);

    try {
      const plannedRun = await planWorkspaceCommand({
        input_text: draft,
        scope_kind: "workspace",
      });
      setRunState(plannedRun);

      if (plannedRun.status !== "planned") {
        setBanner({
          tone: plannedRun.status === "unsupported" ? "error" : "info",
          text: plannedRun.status_reason || translate("agent.command.planFailed"),
        });
        return;
      }

      const executionIds = deriveProposalExecutionIds(plannedRun.plan);
      if (!executionIds?.length) {
        setBanner({
          tone: "info",
          text: translate("agent.command.analysisOnlyDescription"),
        });
        return;
      }

      const executedRun = await executeWorkspaceCommand(plannedRun.command_id, {
        selected_step_ids: executionIds,
      });
      setRunState(executedRun);
      setBanner({
        tone: executedRun.status === "failed" ? "error" : "info",
        text: translate("agent.command.proposalReady"),
      });
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("agent.command.planFailed") });
    } finally {
      setBusy(null);
    }
  }

  async function handleRunAnalysis() {
    if (!run || !analysisExecutionIds?.length) {
      return;
    }
    setBusy("analysis");
    setBanner(null);
    try {
      const nextRun = await executeWorkspaceCommand(run.command_id, {
        selected_step_ids: analysisExecutionIds,
      });
      setRunState(nextRun);
      setBanner({
        tone: nextRun.status === "failed" ? "error" : "info",
        text: nextRun.status_reason || translate("agent.command.executionUpdated"),
      });
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("agent.command.executeFailed") });
    } finally {
      setBusy(null);
    }
  }

  async function handleCreateTicket() {
    if (!proposal) {
      return;
    }
    setTicketBusy("create");
    setBanner(null);
    try {
      const nextTicket = await createApprovalTicket(proposal.proposal_id, "web");
      setTicket(nextTicket);
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("agent.suggestion.notSafeToRunHere") });
    } finally {
      setTicketBusy(null);
    }
  }

  async function handleConfirmTicket() {
    if (!ticket) {
      return;
    }
    setTicketBusy("confirm");
    setBanner(null);
    try {
      const nextTicket = await confirmApprovalTicket(ticket.ticket_id);
      setTicket(nextTicket);
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("agent.ticket.failed") });
    } finally {
      setTicketBusy(null);
    }
  }

  async function handleCancelTicket() {
    if (!ticket) {
      return;
    }
    setTicketBusy("cancel");
    setBanner(null);
    try {
      const nextTicket = await cancelApprovalTicket(ticket.ticket_id);
      setTicket(nextTicket);
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("agent.ticket.failed") });
    } finally {
      setTicketBusy(null);
    }
  }

  async function handleRefreshTicket() {
    if (!ticket) {
      return;
    }
    setTicketBusy("refresh");
    setBanner(null);
    try {
      const nextTicket = await getApprovalTicket(ticket.ticket_id);
      setTicket(nextTicket);
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("agent.suggestion.contextUnavailable") });
    } finally {
      setTicketBusy(null);
    }
  }

  return (
    <Card
      className="relative overflow-hidden border-cobalt/15 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.12),transparent_42%),radial-gradient(circle_at_85%_15%,rgba(31,94,255,0.08),transparent_22%),linear-gradient(180deg,rgba(255,255,255,0.98),rgba(246,249,255,0.96))] p-5 shadow-[0_18px_40px_rgba(20,32,44,0.08)] md:p-6"
      data-testid="agent-command-panel"
    >
      <div className="pointer-events-none absolute inset-x-6 top-0 h-20 bg-[linear-gradient(180deg,rgba(31,94,255,0.08),transparent)]" />
      <div className="relative">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("agent.command.eyebrow")}</p>
            <h2 className="mt-2 text-2xl font-semibold text-ink">{translate("agent.command.title")}</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-[#596270]">{translate("agent.command.summary")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="info">{commandScopeLabel("workspace")}</Badge>
            {run ? <Badge tone={statusTone(run.status)}>{commandRunStatusLabel(run.status)}</Badge> : null}
            <Sparkles className="h-4 w-4 text-cobalt" />
          </div>
        </div>

        <div className={workbenchStateSurfaceClassName("info", "mt-5 animate-surface-enter px-4 py-4")} data-testid="agent-command-guardrail">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="max-w-3xl">
              <p className="text-sm font-medium text-ink">{translate("agent.command.guardrailTitle")}</p>
              <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("agent.command.guardrailDescription")}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge tone="info">{translate("agent.command.boundaryLabels.proposal_or_ticket_chain")}</Badge>
              <Badge tone="info">{translate("agent.command.runMetadata.scope")}: {commandScopeLabel("workspace")}</Badge>
            </div>
          </div>
        </div>

        {banner ? (
          <div className={workbenchStateSurfaceClassName(banner.tone === "error" ? "error" : "info", "mt-4 animate-surface-enter px-4 py-3 text-sm text-[#314051]")}>
            {banner.text}
          </div>
        ) : null}

        <div className="mt-6 grid gap-5 xl:grid-cols-[minmax(0,1.18fr)_320px]">
          <div className={workbenchSupportPanelClassName("default", "animate-surface-enter animate-surface-delay-1 p-5")}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <label className="block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="agent-command-input">
                {translate("agent.command.inputLabel")}
              </label>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="ghost" onClick={focusComposer}>
                  {translate("agent.command.focusComposer")}
                </Button>
                <Button size="sm" variant="ghost" onClick={handleClearCurrentRun} disabled={!canClear}>
                  {translate("agent.command.clearRun")}
                </Button>
              </div>
            </div>
            <Textarea
              ref={composerRef}
              id="agent-command-input"
              value={draft}
              onChange={(event) => onDraftChange(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              placeholder={translate("agent.command.placeholder")}
              className="mt-4 min-h-[188px] border-cobalt/15 bg-white/88"
            />
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={() => void handleGenerateProposal()} disabled={busy === "proposal" || !draft.trim()}>
                  {busy === "proposal" ? translate("agent.command.generatingProposal") : translate("agent.command.generateProposal")}
                </Button>
                {analysisExecutionIds ? (
                  <Button size="sm" variant="soft" onClick={() => void handleRunAnalysis()} disabled={busy === "analysis"}>
                    {busy === "analysis" ? translate("agent.command.runningAnalysis") : translate("agent.command.runAnalysis")}
                  </Button>
                ) : null}
              </div>
              <p className="text-xs text-[#6d7885]">{translate("agent.command.shortcutHint")}</p>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-[#6d7885]">
              {proposalExecutionIds ? <Badge tone="info">{translate("agent.command.proposalFlowHint")}</Badge> : null}
              <span>{analysisExecutionIds ? translate("agent.command.analysisOnlyHint") : translate("agent.command.primaryFlowHint")}</span>
            </div>
          </div>

          <div className="space-y-4">
            {dynamicSuggestions.length > 0 ? (
              <div className={workbenchSupportPanelClassName("info", "animate-surface-enter animate-surface-delay-2 p-4")}>
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("agent.command.contextualSuggestionsTitle")}</p>
                <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("agent.command.contextualSuggestionsSummary")}</p>
                <div className="mt-3 space-y-3">
                  {dynamicSuggestions.map((suggestion) => (
                    <SuggestionCard
                      key={suggestion.id}
                      suggestion={suggestion}
                      onClick={() => handleFillPrompt(suggestion.prompt)}
                      testId={`agent-command-contextual-suggestion-${suggestion.id}`}
                      tone="info"
                    />
                  ))}
                </div>
              </div>
            ) : null}

            {staticSuggestions.length > 0 ? (
              <div className={workbenchSupportPanelClassName("default", "animate-surface-enter animate-surface-delay-3 p-4")}>
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("agent.command.examplesTitle")}</p>
                <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("agent.command.examplesSummary")}</p>
                <div className="mt-3 space-y-3">
                  {staticSuggestions.map((suggestion) => (
                    <SuggestionCard
                      key={suggestion.id}
                      suggestion={suggestion}
                      onClick={() => handleFillPrompt(suggestion.prompt)}
                      testId={`agent-command-suggestion-${suggestion.id}`}
                    />
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>

        {proposal ? (
          <div className="mt-6 animate-surface-enter">
            <AgentProposalCard
              title={proposal.summary}
              proposal={proposal}
              executable={proposal.execution_mode === "approval_ticket_required" && proposal.can_create_ticket}
              blockingConditions={[]}
              onCreateTicket={() => void handleCreateTicket()}
              creatingTicket={ticketBusy === "create"}
              eyebrow={translate("agent.flow.proposal")}
              summaryOnly={Boolean(ticket)}
              executableMessage={translate("agent.command.proposalReadyDescription")}
              webOnlyMessage={translate("agent.command.webOnlyProposalDescription")}
              webOnlyAction={
                proposal.execution_mode === "web_only" ? (
                  <Button asChild size="sm" variant="ghost">
                    <Link href={proposalWebOnlyHref(proposal, basePath)}>{translate("agent.command.openRelatedPage")}</Link>
                  </Button>
                ) : undefined
              }
            />
          </div>
        ) : run?.status === "planned" && !proposalExecutionIds ? (
          <div className={workbenchStateSurfaceClassName("info", "mt-6 animate-surface-enter px-4 py-4")}>
            <p className="text-sm font-medium text-ink">{translate("agent.command.analysisOnlyTitle")}</p>
            <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("agent.command.analysisOnlyDescription")}</p>
          </div>
        ) : null}

        {ticket ? (
          <div className="mt-6 animate-surface-enter">
            <ApprovalTicketBar
              ticket={ticket}
              busy={ticketBusy === "confirm" || ticketBusy === "cancel" || ticketBusy === "refresh" ? ticketBusy : null}
              onConfirm={() => void handleConfirmTicket()}
              onCancel={() => void handleCancelTicket()}
              onRefresh={() => void handleRefreshTicket()}
            />
          </div>
        ) : null}

        {run ? (
          <div className="mt-6 space-y-4">
            <div className={workbenchStateSurfaceClassName("neutral", "animate-surface-enter px-4 py-4")} data-testid="agent-command-run-summary">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 max-w-3xl">
                  <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("agent.command.latestRunEyebrow")}</p>
                  <p className="mt-2 text-sm font-medium text-ink">{run.input_text}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Badge tone="info">{commandScopeLabel(run.scope_kind)}</Badge>
                  <Badge tone={statusTone(run.status)}>{commandRunStatusLabel(run.status)}</Badge>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap gap-3 text-xs text-[#6d7885]">
                <span>{translate("agent.command.runMetadata.scope")}: {commandScopeLabel(run.scope_kind)}</span>
                <span>{translate("agent.command.runMetadata.createdAt")}: {formatDateTime(run.created_at)}</span>
                <span>{translate("agent.command.runMetadata.updatedAt")}: {formatDateTime(run.updated_at)}</span>
                {run.executed_at ? <span>{translate("agent.command.runMetadata.executedAt")}: {formatDateTime(run.executed_at)}</span> : null}
              </div>
              {run.status_reason ? <p className="mt-3 text-sm text-[#596270]">{run.status_reason}</p> : null}
            </div>

            {guidance ? (
              <div
                className={workbenchStateSurfaceClassName(run.status === "unsupported" ? "error" : "info", "animate-surface-enter px-4 py-4")}
                data-testid={`agent-command-guidance-${run.status}`}
              >
                <p className="text-sm font-medium text-ink">{guidance.title}</p>
                <p className="mt-2 text-sm leading-6 text-[#596270]">{guidance.description}</p>
              </div>
            ) : null}

            <AgentDisclosure title={translate("agent.command.planDetailsTitle")}>
              <div className="space-y-3">
                {plannedSteps.length === 0 ? (
                  <CommandEmptyPanel
                    title={translate("agent.command.noStepsTitle")}
                    description={translate("agent.command.noStepsDescription")}
                  />
                ) : (
                  plannedSteps.map((step, index) => {
                    const result = stepResultFor(run, step.step_id);
                    const dependencyText = summarizeStepDependencies(step, stepIndexes);
                    const argFacts = summarizeStepArgs(step.args, stepIndexes);
                    return (
                      <div key={step.step_id} className={workbenchSupportPanelClassName(result?.status === "failed" || result?.status === "blocked" ? "error" : "quiet", "p-4")} data-testid={`agent-command-step-${step.step_id}`}>
                        <div className="flex items-start gap-3">
                          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[rgba(20,32,44,0.06)] text-xs font-semibold text-ink">
                            {index + 1}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <p className="text-sm font-medium text-ink">{step.title}</p>
                              <Badge tone="info">{commandToolLabel(step.tool_name)}</Badge>
                              <Badge tone={riskTone(step.risk_level)}>{formatStatusLabel(step.risk_level)}</Badge>
                              <Badge tone={statusTone(result?.status || "pending")}>
                                {commandStepStatusLabel((result?.status || "pending") as AgentCommandExecutionResult["status"])}
                              </Badge>
                            </div>
                            <p className="mt-2 text-sm leading-6 text-[#596270]">{step.reason}</p>
                            <div className="mt-3 flex flex-wrap gap-3 text-xs text-[#6d7885]">
                              <span>{translate("agent.command.targetKind")}: {commandTargetKindLabel(step.target_kind)}</span>
                              <span>{translate("agent.command.executionBoundary")}: {commandBoundaryLabel(step.execution_boundary)}</span>
                              {dependencyText ? <span>{translate("agent.command.dependsOn")}: {dependencyText}</span> : null}
                            </div>
                            {argFacts.length > 0 ? (
                              <div className="mt-3">
                                <p className="text-xs uppercase tracking-[0.14em] text-[#6d7885]">{translate("agent.command.argumentsTitle")}</p>
                                <div className="mt-2 flex flex-wrap gap-2 text-xs text-[#596270]">
                                  {argFacts.map((fact) => (
                                    <span key={`${step.step_id}-${fact}`} className="rounded-full border border-line/70 bg-white/70 px-2.5 py-1">
                                      {fact}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            ) : null}
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </AgentDisclosure>

            <AgentDisclosure title={translate("agent.command.resultsDetailsTitle")}>
              <div className="space-y-3">
                {displayResults.length === 0 ? (
                  <CommandEmptyPanel
                    title={translate("agent.command.noResultsTitle")}
                    description={translate("agent.command.noResultsDescription")}
                  />
                ) : (
                  displayResults.map((result) => {
                    const step = plannedSteps.find((row) => row.step_id === result.step_id) || null;
                    const facts = summarizeOutputSummary(result.output_summary);
                    return (
                      <div
                        key={`result-${result.step_id}`}
                        className={workbenchSupportPanelClassName(result.status === "failed" || result.status === "blocked" ? "error" : "quiet", "p-4")}
                        data-testid={`agent-command-result-${result.step_id}`}
                      >
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <p className="text-sm font-medium text-ink">
                                {step?.title || translate("agent.command.resultFallbackTitle", { stepId: result.step_id })}
                              </p>
                              <Badge tone={statusTone(result.status)}>{commandStepStatusLabel(result.status)}</Badge>
                            </div>
                            {step ? <p className="mt-2 text-xs text-[#6d7885]">{commandToolLabel(step.tool_name)}</p> : null}
                          </div>
                        </div>
                        {facts.length > 0 ? (
                          <div className="mt-3 flex flex-wrap gap-2 text-xs text-[#596270]">
                            {facts.map((fact) => (
                              <span key={`${result.step_id}-${fact}`} className="rounded-full border border-line/70 bg-white/70 px-2.5 py-1">
                                {fact}
                              </span>
                            ))}
                          </div>
                        ) : null}
                        <div className="mt-3 flex flex-wrap gap-3 text-xs text-[#6d7885]">
                          {result.started_at ? <span>{translate("agent.command.resultLabels.startedAt")}: {formatDateTime(result.started_at)}</span> : null}
                          {result.finished_at ? <span>{translate("agent.command.resultLabels.finishedAt")}: {formatDateTime(result.finished_at)}</span> : null}
                        </div>
                        {result.error_text ? (
                          <div className={workbenchStateSurfaceClassName("error", "mt-3 px-4 py-3 text-sm text-[#314051]")}>
                            {result.error_text}
                          </div>
                        ) : null}
                      </div>
                    );
                  })
                )}
              </div>
            </AgentDisclosure>
          </div>
        ) : null}
      </div>
    </Card>
  );
}
