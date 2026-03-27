from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from app.modules.agents.command_registry import COMMAND_TOOL_SPEC_BY_NAME, planner_tool_catalog
from app.modules.agents.language_context import AgentLanguageContext
from app.modules.llm_gateway import LlmGatewayError, LlmInvokeRequest, invoke_llm_json


_COMMAND_PLANNER_SYSTEM_PROMPT = """
You plan bounded CalendarDIFF workspace actions from a user's freeform command.

Return JSON only.

Rules:
- Use only the allowed tools provided in tool_catalog.
- Do not invent tool names.
- Do not invent unknown IDs.
- If the target is ambiguous, return status=clarification_required.
- If the intent is outside the allowed tool catalog, return status=unsupported.
- If the intent is actionable, return status=planned.
- All mutating business actions must stay inside the existing proposal/ticket chain.
- Never create direct write steps that bypass proposals or approval tickets.
- Use execution_boundary=read_only for read tools.
- Use execution_boundary=proposal_or_ticket_chain for mutating tools.
- Use depends_on to order multi-step plans.
- For later steps that depend on earlier outputs, use args references in this exact form:
  {"$ref":"step_id.field_name"}
  Example:
  {"proposal_id":{"$ref":"step_1.proposal_id"}}
- Keep the plan compact. Include only the steps actually needed.

Planning patterns:
- "review workspace / what should I do" -> read tools only.
- "approve change" -> create_change_decision_proposal -> create_approval_ticket -> confirm_approval_ticket.
- "reject change" -> create_change_decision_proposal -> create_approval_ticket -> confirm_approval_ticket.
- "edit proposal then approve" -> create_change_edit_commit_proposal -> create_approval_ticket -> confirm_approval_ticket.
- "inspect source / inspect family / inspect change" -> matching read context tool.
- "retry or recover source" -> create_source_recovery_proposal.
- "family relink preview" -> create_family_relink_preview_proposal.
- "family relink commit" -> create_family_relink_commit_proposal -> create_approval_ticket -> confirm_approval_ticket.
- "label learning commit" -> create_label_learning_commit_proposal -> create_approval_ticket -> confirm_approval_ticket.
- "confirm ticket" -> get_approval_ticket -> confirm_approval_ticket.
- "cancel ticket" -> get_approval_ticket -> cancel_approval_ticket.

Output schema:
{
  "status": "planned|clarification_required|unsupported",
  "status_reason": "short user-facing explanation",
  "steps": [
    {
      "step_id": "step_1",
      "title": "short title",
      "reason": "short reason",
      "tool_name": "allowed_tool_name",
      "target_kind": "workspace|change|source|family|proposal|ticket",
      "args": {},
      "depends_on": ["step_1"],
      "risk_level": "low|medium|high",
      "execution_boundary": "read_only|proposal_or_ticket_chain"
    }
  ]
}
"""


class PlannedStep(BaseModel):
    step_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=600)
    tool_name: str = Field(min_length=1, max_length=128)
    target_kind: str = Field(min_length=1, max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    risk_level: str = Field(pattern="^(low|medium|high)$")
    execution_boundary: str = Field(pattern="^(read_only|proposal_or_ticket_chain)$")

    model_config = {"extra": "forbid"}


class CommandPlanEnvelope(BaseModel):
    status: str = Field(pattern="^(planned|clarification_required|unsupported)$")
    status_reason: str = Field(min_length=1, max_length=1000)
    steps: list[PlannedStep] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _validate_steps(self) -> "CommandPlanEnvelope":
        if self.status != "planned" and self.steps:
            raise ValueError("non-planned command responses must not include steps")
        seen: set[str] = set()
        for index, step in enumerate(self.steps):
            if step.step_id in seen:
                raise ValueError(f"duplicate step_id: {step.step_id}")
            seen.add(step.step_id)
            if step.tool_name not in COMMAND_TOOL_SPEC_BY_NAME:
                raise ValueError(f"unsupported tool_name: {step.tool_name}")
            spec = COMMAND_TOOL_SPEC_BY_NAME[step.tool_name]
            if step.execution_boundary != spec.execution_boundary:
                raise ValueError(f"execution_boundary mismatch for {step.tool_name}")
            for dep in step.depends_on:
                if dep not in seen:
                    raise ValueError(f"depends_on must reference an earlier step: {dep}")
            _validate_step_args(step.args)
            if index == 0 and step.depends_on:
                raise ValueError("first step cannot depend on an earlier step")
        return self


def generate_command_plan(
    db: Session,
    *,
    command_id: str,
    input_text: str,
    language_context: AgentLanguageContext,
    scope_snapshot: dict[str, Any],
) -> dict[str, Any]:
    try:
        llm_result = invoke_llm_json(
            db,
            invoke_request=LlmInvokeRequest(
                task_name="agent_workspace_command_plan",
                system_prompt=_COMMAND_PLANNER_SYSTEM_PROMPT,
                user_payload={
                    "product": "CalendarDIFF",
                    "command_id": command_id,
                    "target_language_code": language_context.effective_language_code,
                    "system_language_code": language_context.system_language_code,
                    "input_language_code": language_context.input_language_code,
                    "language_resolution_source": language_context.resolution_source,
                    "input_text": input_text,
                    "scope_snapshot": scope_snapshot,
                    "tool_catalog": planner_tool_catalog(),
                },
                output_schema_name="AgentWorkspaceCommandPlan",
                output_schema_json=CommandPlanEnvelope.model_json_schema(),
                profile_family="agent",
                request_id=command_id,
                temperature=0.0,
                session_cache_mode="disable",
            ),
        )
        payload = CommandPlanEnvelope.model_validate(llm_result.json_object)
        return payload.model_dump(mode="json")
    except (LlmGatewayError, ValidationError, ValueError):
        return _fallback_command_plan(
            input_text=input_text,
            language_code=language_context.effective_language_code,
        )


def _validate_step_args(value: Any) -> None:
    if isinstance(value, dict):
        if "$ref" in value:
            if len(value) != 1 or not isinstance(value["$ref"], str) or "." not in value["$ref"]:
                raise ValueError("invalid args $ref")
            return
        for nested in value.values():
            _validate_step_args(nested)
        return
    if isinstance(value, list):
        for nested in value:
            _validate_step_args(nested)


def _fallback_command_plan(*, input_text: str, language_code: str) -> dict[str, Any]:
    normalized = str(input_text or "").strip()
    if not normalized:
        return {
            "status": "clarification_required",
            "status_reason": "请输入你想让我执行或规划的工作区操作。" if language_code == "zh-CN" else "Tell me which workspace action you want me to plan.",
            "steps": [],
        }
    return {
        "status": "unsupported",
        "status_reason": (
            "这条命令目前还不能稳定映射到受限工具集，请换成更明确的工作区操作。"
            if language_code == "zh-CN"
            else "I could not safely map that request onto the bounded workspace tools yet."
        ),
        "steps": [],
    }

