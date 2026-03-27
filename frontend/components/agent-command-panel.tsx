"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, Sparkles } from "lucide-react";
import { planWorkspaceCommand, executeWorkspaceCommand } from "@/lib/api/agents";
import type { AgentCommandSuggestion } from "@/lib/agent-command-suggestions";
import {
  commandBoundaryLabel,
  commandRunStatusLabel,
  commandScopeLabel,
  commandStepStatusLabel,
  commandTargetKindLabel,
  commandToolLabel,
  executeDisabledReason,
  runGuidanceCopy,
  stepIndexLookup,
  summarizeOutputSummary,
  summarizeStepArgs,
  summarizeStepDependencies,
} from "@/lib/agent-command-presenters";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { translate } from "@/lib/i18n/runtime";
import { formatDateTime, formatStatusLabel } from "@/lib/presenters";
import type { AgentCommandExecutionResult, AgentCommandRun } from "@/lib/types";
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

type AgentCommandPanelProps = {
  draft: string;
  onDraftChange: (nextValue: string) => void;
  suggestions?: AgentCommandSuggestion[];
  focusRequestToken?: number;
  onRunUpdated?: (run: AgentCommandRun) => void;
};

export function AgentCommandPanel({
  draft,
  onDraftChange,
  suggestions = EMPTY_SUGGESTIONS,
  focusRequestToken = 0,
  onRunUpdated,
}: AgentCommandPanelProps) {
  const [run, setRun] = useState<AgentCommandRun | null>(null);
  const [busy, setBusy] = useState<"plan" | "execute" | null>(null);
  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [selectedStepIds, setSelectedStepIds] = useState<Set<string>>(new Set());
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

  const plannedSteps = useMemo(() => run?.plan || EMPTY_STEPS, [run]);
  const selectedCount = selectedStepIds.size;
  const stepIndexes = useMemo(() => stepIndexLookup(plannedSteps), [plannedSteps]);
  const remainingSelectableCount = useMemo(
    () => plannedSteps.filter((step) => stepResultFor(run, step.step_id)?.status !== "succeeded").length,
    [plannedSteps, run],
  );
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
  const canExecute = Boolean(
    run &&
      plannedSteps.length > 0 &&
      selectedCount > 0 &&
      busy !== "execute" &&
      run.status !== "clarification_required" &&
      run.status !== "unsupported" &&
      run.status !== "executing",
  );
  const canClear = Boolean(run || draft.trim() || banner);
  const executeHint = useMemo(
    () =>
      executeDisabledReason({
        run,
        stepCount: plannedSteps.length,
        remainingCount: remainingSelectableCount,
        selectedCount,
        busy,
      }),
    [busy, plannedSteps.length, remainingSelectableCount, run, selectedCount],
  );
  const selectionSummary = useMemo(
    () =>
      translate("agent.command.selectionSummary", {
        selected: String(selectedCount),
        remaining: String(remainingSelectableCount),
      }),
    [remainingSelectableCount, selectedCount],
  );

  useEffect(() => {
    if (!focusRequestToken) {
      return;
    }
    composerRef.current?.focus();
    composerRef.current?.scrollIntoView({ block: "nearest" });
  }, [focusRequestToken]);

  function focusComposer() {
    composerRef.current?.focus();
    composerRef.current?.scrollIntoView({ block: "nearest" });
  }

  function setRunAndSelection(nextRun: AgentCommandRun) {
    setRun(nextRun);
    const remaining = nextRun.plan
      .filter((step) => {
        const result = stepResultFor(nextRun, step.step_id);
        return result?.status !== "succeeded";
      })
      .map((step) => step.step_id);
    setSelectedStepIds(new Set(remaining));
    onRunUpdated?.(nextRun);
  }

  function handleFillPrompt(prompt: string) {
    onDraftChange(prompt);
    setBanner(null);
    focusComposer();
  }

  function handleClearCurrentRun() {
    setRun(null);
    setBanner(null);
    setSelectedStepIds(new Set());
    onDraftChange("");
    focusComposer();
  }

  function handleComposerKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && draft.trim() && busy !== "plan") {
      event.preventDefault();
      void handlePlan();
    }
  }

  async function handlePlan() {
    setBusy("plan");
    setBanner(null);
    try {
      const nextRun = await planWorkspaceCommand({
        input_text: draft,
        scope_kind: "workspace",
      });
      setRunAndSelection(nextRun);
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("agent.command.planFailed") });
    } finally {
      setBusy(null);
    }
  }

  async function handleExecute() {
    if (!run) {
      return;
    }
    setBusy("execute");
    setBanner(null);
    try {
      const nextRun = await executeWorkspaceCommand(run.command_id, {
        selected_step_ids: Array.from(selectedStepIds),
      });
      setRunAndSelection(nextRun);
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

  function toggleStep(stepId: string, checked: boolean) {
    setSelectedStepIds((current) => {
      const next = new Set(current);
      if (checked) {
        next.add(stepId);
      } else {
        next.delete(stepId);
      }
      return next;
    });
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
                <Button size="sm" onClick={() => void handlePlan()} disabled={busy === "plan" || !draft.trim()}>
                  {busy === "plan" ? translate("agent.command.planning") : translate("agent.command.plan")}
                </Button>
                <Button size="sm" variant="soft" onClick={() => void handleExecute()} disabled={!canExecute}>
                  {busy === "execute"
                    ? translate("agent.command.executing")
                    : translate("agent.command.executeSelected", { count: String(selectedCount) })}
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </div>
              <p className="text-xs text-[#6d7885]">{translate("agent.command.shortcutHint")}</p>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-[#6d7885]">
              {run ? <Badge tone="info">{selectionSummary}</Badge> : null}
              <span>{executeHint}</span>
            </div>
          </div>

          <div className="space-y-4">
            {staticSuggestions.length > 0 ? (
              <div className={workbenchSupportPanelClassName("default", "animate-surface-enter animate-surface-delay-2 p-4")}>
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

            {dynamicSuggestions.length > 0 ? (
              <div className={workbenchSupportPanelClassName("info", "animate-surface-enter animate-surface-delay-3 p-4")}>
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
          </div>
        </div>

        <div className="mt-6 grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,0.92fr)]">
          <div className="space-y-4">
            {run ? (
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
            ) : null}

            <div className={workbenchSupportPanelClassName("default", "animate-surface-enter p-4")}>
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("agent.command.planSectionEyebrow")}</p>
                <h3 className="mt-2 text-base font-semibold text-ink">{translate("agent.command.planSectionTitle")}</h3>
                <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("agent.command.planSectionSummary")}</p>
              </div>
              <div className="mt-4 space-y-3">
                {!run ? (
                  <CommandEmptyPanel
                    title={translate("agent.command.emptyTitle")}
                    description={translate("agent.command.emptyDescription")}
                  />
                ) : plannedSteps.length === 0 ? (
                  <CommandEmptyPanel
                    title={translate("agent.command.noStepsTitle")}
                    description={translate("agent.command.noStepsDescription")}
                  />
                ) : (
                  plannedSteps.map((step, index) => {
                    const result = stepResultFor(run, step.step_id);
                    const checked = selectedStepIds.has(step.step_id);
                    const dependencyText = summarizeStepDependencies(step, stepIndexes);
                    const argFacts = summarizeStepArgs(step.args, stepIndexes);
                    const cardTone = result?.status === "failed" || result?.status === "blocked" ? "error" : checked ? "info" : "quiet";
                    return (
                      <div key={step.step_id} className={workbenchSupportPanelClassName(cardTone, "interactive-lift p-4")} data-testid={`agent-command-step-${step.step_id}`}>
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
                          <Checkbox
                            aria-label={step.title}
                            checked={checked}
                            disabled={result?.status === "succeeded" || busy === "execute" || run?.status === "executing"}
                            onChange={(event) => toggleStep(step.step_id, event.currentTarget.checked)}
                            className="mt-1"
                          />
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>

          <div className="space-y-4">
            {guidance ? (
              <div
                className={workbenchStateSurfaceClassName(run?.status === "unsupported" ? "error" : "info", "animate-surface-enter px-4 py-4")}
                data-testid={`agent-command-guidance-${run?.status || "none"}`}
              >
                <p className="text-sm font-medium text-ink">{guidance.title}</p>
                <p className="mt-2 text-sm leading-6 text-[#596270]">{guidance.description}</p>
              </div>
            ) : null}

            <div className={workbenchSupportPanelClassName("default", "animate-surface-enter p-4")}>
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("agent.command.resultsSectionEyebrow")}</p>
                <h3 className="mt-2 text-base font-semibold text-ink">{translate("agent.command.resultsSectionTitle")}</h3>
                <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("agent.command.resultsSectionSummary")}</p>
              </div>
              <div className="mt-4 space-y-3">
                {!run || displayResults.length === 0 ? (
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
                        className={workbenchSupportPanelClassName(result.status === "failed" || result.status === "blocked" ? "error" : "quiet", "interactive-lift p-4")}
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
            </div>
          </div>
        </div>
      </div>
    </Card>
  );
}
