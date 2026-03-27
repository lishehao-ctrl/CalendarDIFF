"use client";

import { useMemo, useState } from "react";
import { ArrowRight, Sparkles } from "lucide-react";
import { planWorkspaceCommand, executeWorkspaceCommand } from "@/lib/api/agents";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/data-states";
import { translate } from "@/lib/i18n/runtime";
import type { AgentCommandExecutionResult, AgentCommandRun, AgentCommandStep } from "@/lib/types";
import { workbenchSupportPanelClassName, workbenchStateSurfaceClassName } from "@/lib/workbench-styles";

function statusTone(status: string) {
  switch (status) {
    case "completed":
    case "succeeded":
      return "approved";
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

function stepResultFor(run: AgentCommandRun | null, stepId: string): AgentCommandExecutionResult | null {
  if (!run) {
    return null;
  }
  return run.execution_results.find((row) => row.step_id === stepId) || null;
}

function outputSummaryText(result: AgentCommandExecutionResult | null) {
  if (!result || !result.output_summary || Object.keys(result.output_summary).length === 0) {
    return null;
  }
  return Object.entries(result.output_summary)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(" · ");
}

export function AgentCommandPanel({
  onRunUpdated,
}: {
  onRunUpdated?: (run: AgentCommandRun) => void;
}) {
  const [inputText, setInputText] = useState("");
  const [run, setRun] = useState<AgentCommandRun | null>(null);
  const [busy, setBusy] = useState<"plan" | "execute" | null>(null);
  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [selectedStepIds, setSelectedStepIds] = useState<Set<string>>(new Set());

  const plannedSteps = run?.plan || [];
  const selectedCount = selectedStepIds.size;
  const canExecute = Boolean(run && plannedSteps.length > 0 && selectedCount > 0 && busy !== "execute");

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

  async function handlePlan() {
    setBusy("plan");
    setBanner(null);
    try {
      const nextRun = await planWorkspaceCommand({
        input_text: inputText,
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
    <Card className="p-5" data-testid="agent-command-panel">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-3xl">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("agent.command.eyebrow")}</p>
          <h2 className="mt-2 text-xl font-semibold text-ink">{translate("agent.command.title")}</h2>
          <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("agent.command.summary")}</p>
        </div>
        <div className="flex items-center gap-2">
          {run ? <Badge tone={statusTone(run.status)}>{run.status.replaceAll("_", " ")}</Badge> : null}
          <Sparkles className="h-4 w-4 text-[#6d7885]" />
        </div>
      </div>

      {banner ? (
        <div className={workbenchStateSurfaceClassName(banner.tone === "error" ? "error" : "info", "mt-4 px-4 py-3 text-sm text-[#314051]")}>
          {banner.text}
        </div>
      ) : null}

      <div className="mt-5 space-y-3">
        <label className="block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="agent-command-input">
          {translate("agent.command.inputLabel")}
        </label>
        <Textarea
          id="agent-command-input"
          value={inputText}
          onChange={(event) => setInputText(event.target.value)}
          placeholder={translate("agent.command.placeholder")}
          className="min-h-[108px]"
        />
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => void handlePlan()} disabled={busy === "plan" || !inputText.trim()}>
            {busy === "plan" ? translate("agent.command.planning") : translate("agent.command.plan")}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => void handleExecute()} disabled={!canExecute}>
            {busy === "execute"
              ? translate("agent.command.executing")
              : translate("agent.command.executeSelected", { count: String(selectedCount) })}
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="mt-5 space-y-3">
        {!run ? (
          <EmptyState
            title={translate("agent.command.emptyTitle")}
            description={translate("agent.command.emptyDescription")}
          />
        ) : (
          <>
            <div className="rounded-[1rem] border border-line/80 bg-white/70 px-4 py-3 text-sm text-[#314051]">
              <span className="font-medium text-ink">{translate("agent.command.latestStatus")}: </span>
              <span>{run.status.replaceAll("_", " ")}</span>
              {run.status_reason ? <p className="mt-2 text-[#596270]">{run.status_reason}</p> : null}
            </div>
            {plannedSteps.length === 0 ? (
              <EmptyState
                title={translate("agent.command.noStepsTitle")}
                description={translate("agent.command.noStepsDescription")}
              />
            ) : (
              plannedSteps.map((step) => {
                const result = stepResultFor(run, step.step_id);
                const checked = selectedStepIds.has(step.step_id);
                return (
                  <div key={step.step_id} className={workbenchSupportPanelClassName("quiet", "p-4")} data-testid={`agent-command-step-${step.step_id}`}>
                    <div className="flex items-start gap-3">
                      <Checkbox
                        aria-label={step.title}
                        checked={checked}
                        disabled={result?.status === "succeeded" || busy === "execute"}
                        onChange={(event) => toggleStep(step.step_id, event.currentTarget.checked)}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-sm font-medium text-ink">{step.title}</p>
                          <Badge tone="info">{step.tool_name}</Badge>
                          <Badge tone={statusTone(step.risk_level)}>{step.risk_level}</Badge>
                          <Badge tone={statusTone(result?.status || "pending")}>{(result?.status || "pending").replaceAll("_", " ")}</Badge>
                        </div>
                        <p className="mt-2 text-sm leading-6 text-[#596270]">{step.reason}</p>
                        <div className="mt-2 flex flex-wrap gap-3 text-xs text-[#6d7885]">
                          <span>{translate("agent.command.targetKind")}: {step.target_kind}</span>
                          <span>{translate("agent.command.executionBoundary")}: {step.execution_boundary.replaceAll("_", " ")}</span>
                          {step.depends_on.length > 0 ? <span>{translate("agent.command.dependsOn")}: {step.depends_on.join(", ")}</span> : null}
                        </div>
                        {outputSummaryText(result) ? (
                          <p className="mt-2 text-xs text-[#596270]">{outputSummaryText(result)}</p>
                        ) : null}
                        {result?.error_text ? <p className="mt-2 text-xs text-[#8a472d]">{result.error_text}</p> : null}
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </>
        )}
      </div>
    </Card>
  );
}
