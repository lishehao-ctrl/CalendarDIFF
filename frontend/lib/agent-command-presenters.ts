import { translate } from "@/lib/i18n/runtime";
import { formatStatusLabel } from "@/lib/presenters";
import type {
  AgentCommandExecutionBoundary,
  AgentCommandRunStatus,
  AgentCommandScopeKind,
  AgentCommandStep,
  AgentCommandStepExecutionStatus,
} from "@/lib/types";

type StepIndexLookup = Map<string, number>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isStepRef(value: unknown): value is { $ref: string } {
  return isRecord(value) && typeof value.$ref === "string" && value.$ref.includes(".");
}

function stepLabelFromRef(ref: string, stepIndexes: StepIndexLookup) {
  const stepId = ref.split(".")[0] || "";
  const stepIndex = stepIndexes.get(stepId);
  if (stepIndex == null) {
    return translate("agent.command.referenceUnknown");
  }
  return translate("agent.command.referenceStep", { step: String(stepIndex + 1) });
}

export function commandRunStatusLabel(status: AgentCommandRunStatus) {
  return translate(`agent.command.runStatusLabels.${status}`);
}

export function commandStepStatusLabel(status: AgentCommandStepExecutionStatus) {
  return translate(`agent.command.stepStatusLabels.${status}`);
}

export function commandToolLabel(toolName: string) {
  return translate(`agent.command.toolLabels.${toolName}`);
}

export function commandScopeLabel(scopeKind: AgentCommandScopeKind) {
  return translate(`agent.command.scopeLabels.${scopeKind}`);
}

export function commandBoundaryLabel(boundary: AgentCommandExecutionBoundary) {
  return translate(`agent.command.boundaryLabels.${boundary}`);
}

export function commandTargetKindLabel(targetKind: string) {
  return translate(`agent.command.targetLabels.${targetKind}`);
}

export function stepIndexLookup(plan: AgentCommandStep[]): StepIndexLookup {
  return new Map(plan.map((step, index) => [step.step_id, index]));
}

function entityReferenceLabel(key: string, value: string | number) {
  switch (key) {
    case "change_id":
      return translate("agent.command.targetValue.change", { id: String(value) });
    case "source_id":
      return translate("agent.command.targetValue.source", { id: String(value) });
    case "family_id":
      return translate("agent.command.targetValue.family", { id: String(value) });
    case "proposal_id":
      return translate("agent.command.targetValue.proposal", { id: String(value) });
    case "ticket_id":
      return translate("agent.command.targetValue.ticket", { id: String(value) });
    case "raw_type_id":
      return translate("agent.command.targetValue.rawType", { id: String(value) });
    default:
      return `${key}: ${String(value)}`;
  }
}

function labeledFact(labelKey: string, value: string) {
  return `${translate(labelKey)}: ${value}`;
}

export function summarizeStepDependencies(step: AgentCommandStep, stepIndexes: StepIndexLookup) {
  if (step.depends_on.length === 0) {
    return null;
  }
  return step.depends_on
    .map((stepId) => {
      const index = stepIndexes.get(stepId);
      return index == null
        ? translate("agent.command.referenceUnknown")
        : translate("agent.command.referenceStep", { step: String(index + 1) });
    })
    .join(" · ");
}

export function summarizeStepArgs(args: Record<string, unknown>, stepIndexes: StepIndexLookup) {
  const facts: string[] = [];

  for (const key of ["change_id", "source_id", "family_id", "proposal_id", "ticket_id", "raw_type_id"] as const) {
    const value = args[key];
    if (typeof value === "string" || typeof value === "number") {
      facts.push(entityReferenceLabel(key, value));
      continue;
    }
    if (isStepRef(value)) {
      facts.push(labeledFact(`agent.command.argLabels.${key}`, stepLabelFromRef(value.$ref, stepIndexes)));
    }
  }

  const patch = args.patch;
  if (isRecord(patch)) {
    if (typeof patch.event_name === "string" && patch.event_name.trim()) {
      facts.push(labeledFact("agent.command.argLabels.event_name", patch.event_name.trim()));
    }
    if (typeof patch.due_date === "string" && patch.due_date.trim()) {
      facts.push(labeledFact("agent.command.argLabels.due_date", patch.due_date.trim()));
    }
    if (typeof patch.due_time === "string" && patch.due_time.trim()) {
      facts.push(labeledFact("agent.command.argLabels.due_time", patch.due_time.trim()));
    }
    if (typeof patch.time_precision === "string" && patch.time_precision.trim()) {
      facts.push(
        labeledFact("agent.command.argLabels.time_precision", formatStatusLabel(patch.time_precision.trim())),
      );
    }
  }

  for (const key of ["limit", "review_bucket", "intake_phase", "status", "channel"] as const) {
    const value = args[key];
    if (typeof value === "string" && value.trim()) {
      facts.push(labeledFact(`agent.command.argLabels.${key}`, formatStatusLabel(value.trim(), value.trim())));
    } else if (typeof value === "number") {
      facts.push(labeledFact(`agent.command.argLabels.${key}`, String(value)));
    }
  }

  const unknownKeys = Object.keys(args).filter(
    (key) =>
      ![
        "change_id",
        "source_id",
        "family_id",
        "proposal_id",
        "ticket_id",
        "raw_type_id",
        "patch",
        "limit",
        "review_bucket",
        "intake_phase",
        "status",
        "channel",
      ].includes(key),
  );
  if (unknownKeys.length > 0) {
    facts.push(labeledFact("agent.command.argLabels.other", unknownKeys.join(", ")));
  }

  return facts;
}

export function summarizeOutputSummary(outputSummary: Record<string, unknown>) {
  const facts: string[] = [];
  const summary = typeof outputSummary.summary === "string" ? outputSummary.summary.trim() : "";
  if (summary) {
    facts.push(labeledFact("agent.command.resultLabels.summary", summary));
  }
  if (typeof outputSummary.status === "string" && outputSummary.status.trim()) {
    facts.push(
      labeledFact(
        "agent.command.resultLabels.status",
        formatStatusLabel(outputSummary.status.trim(), outputSummary.status.trim()),
      ),
    );
  }
  for (const key of ["proposal_id", "ticket_id"] as const) {
    const value = outputSummary[key];
    if (typeof value === "string" || typeof value === "number") {
      facts.push(entityReferenceLabel(key, value));
    }
  }
  const targetKind = typeof outputSummary.target_kind === "string" ? outputSummary.target_kind.trim() : "";
  const targetId = outputSummary.target_id;
  if (targetKind && (typeof targetId === "string" || typeof targetId === "number")) {
    facts.push(
      labeledFact(
        "agent.command.resultLabels.target",
        `${commandTargetKindLabel(targetKind)} #${String(targetId)}`,
      ),
    );
  }
  if (typeof outputSummary.risk_level === "string" && outputSummary.risk_level.trim()) {
    facts.push(
      labeledFact(
        "agent.command.resultLabels.risk",
        formatStatusLabel(outputSummary.risk_level.trim(), outputSummary.risk_level.trim()),
      ),
    );
  }
  if (typeof outputSummary.item_count === "number") {
    facts.push(labeledFact("agent.command.resultLabels.itemCount", String(outputSummary.item_count)));
  }
  if (typeof outputSummary.first_item_id === "string" || typeof outputSummary.first_item_id === "number") {
    facts.push(labeledFact("agent.command.resultLabels.firstItemId", String(outputSummary.first_item_id)));
  }
  const unknownKeys = Object.keys(outputSummary).filter(
    (key) =>
      ![
        "summary",
        "status",
        "proposal_id",
        "ticket_id",
        "target_kind",
        "target_id",
        "risk_level",
        "item_count",
        "first_item_id",
        "summary_code",
        "command_id",
      ].includes(key),
  );
  if (unknownKeys.length > 0) {
    facts.push(labeledFact("agent.command.resultLabels.otherFields", unknownKeys.join(", ")));
  }
  return facts;
}

export function runGuidanceCopy(status: AgentCommandRunStatus) {
  if (status === "clarification_required") {
    return {
      title: translate("agent.command.guidance.clarificationTitle"),
      description: translate("agent.command.guidance.clarificationDescription"),
    };
  }
  if (status === "unsupported") {
    return {
      title: translate("agent.command.guidance.unsupportedTitle"),
      description: translate("agent.command.guidance.unsupportedDescription"),
    };
  }
  return null;
}

export function executeDisabledReason({
  run,
  stepCount,
  remainingCount,
  selectedCount,
  busy,
}: {
  run: { status: AgentCommandRunStatus } | null;
  stepCount: number;
  remainingCount: number;
  selectedCount: number;
  busy: "plan" | "execute" | null;
}) {
  if (!run) {
    return translate("agent.command.executeHints.planFirst");
  }
  if (busy === "execute" || run.status === "executing") {
    return translate("agent.command.executeHints.executing");
  }
  if (run.status === "clarification_required") {
    return translate("agent.command.executeHints.clarification");
  }
  if (run.status === "unsupported") {
    return translate("agent.command.executeHints.unsupported");
  }
  if (stepCount === 0) {
    return translate("agent.command.executeHints.noExecutableSteps");
  }
  if (remainingCount === 0) {
    return translate("agent.command.executeHints.allDone");
  }
  if (selectedCount === 0) {
    return translate("agent.command.executeHints.selectSteps");
  }
  return translate("agent.command.executeHints.ready");
}
