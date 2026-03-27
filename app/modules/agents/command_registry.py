from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


AgentCommandScopeKind = Literal["workspace", "change", "source", "family"]
AgentCommandTargetKind = Literal["workspace", "change", "source", "family", "proposal", "ticket"]
AgentCommandExecutionBoundary = Literal["read_only", "proposal_or_ticket_chain"]


@dataclass(frozen=True)
class CommandToolSpec:
    tool_name: str
    target_kind: AgentCommandTargetKind
    execution_boundary: AgentCommandExecutionBoundary
    mutating: bool
    description: str
    args_schema_hint: dict[str, str]
    supports_user_direct: bool = True

    def to_planner_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["args_schema_hint"] = dict(self.args_schema_hint)
        return payload


COMMAND_TOOL_SPECS: tuple[CommandToolSpec, ...] = (
    CommandToolSpec(
        tool_name="get_workspace_context",
        target_kind="workspace",
        execution_boundary="read_only",
        mutating=False,
        description="Read the aggregate workspace context.",
        args_schema_hint={},
    ),
    CommandToolSpec(
        tool_name="get_recent_agent_activity",
        target_kind="workspace",
        execution_boundary="read_only",
        mutating=False,
        description="Read recent proposals and approval tickets.",
        args_schema_hint={"limit": "integer optional"},
    ),
    CommandToolSpec(
        tool_name="list_pending_changes",
        target_kind="workspace",
        execution_boundary="read_only",
        mutating=False,
        description="Read pending changes in the workspace.",
        args_schema_hint={
            "limit": "integer optional",
            "review_bucket": "string optional",
            "intake_phase": "string optional",
        },
    ),
    CommandToolSpec(
        tool_name="list_sources",
        target_kind="workspace",
        execution_boundary="read_only",
        mutating=False,
        description="Read sources in the workspace.",
        args_schema_hint={"status": "string optional"},
    ),
    CommandToolSpec(
        tool_name="get_change_context",
        target_kind="change",
        execution_boundary="read_only",
        mutating=False,
        description="Read detailed context for a specific change.",
        args_schema_hint={"change_id": "integer required"},
    ),
    CommandToolSpec(
        tool_name="get_source_context",
        target_kind="source",
        execution_boundary="read_only",
        mutating=False,
        description="Read detailed context for a specific source.",
        args_schema_hint={"source_id": "integer required"},
    ),
    CommandToolSpec(
        tool_name="get_family_context",
        target_kind="family",
        execution_boundary="read_only",
        mutating=False,
        description="Read detailed context for a specific family.",
        args_schema_hint={"family_id": "integer required"},
    ),
    CommandToolSpec(
        tool_name="create_change_decision_proposal",
        target_kind="change",
        execution_boundary="proposal_or_ticket_chain",
        mutating=True,
        description="Create a change-decision proposal for one change.",
        args_schema_hint={"change_id": "integer required"},
    ),
    CommandToolSpec(
        tool_name="create_change_edit_commit_proposal",
        target_kind="change",
        execution_boundary="proposal_or_ticket_chain",
        mutating=True,
        description="Create a proposal-edit commit proposal for one pending change.",
        args_schema_hint={
            "change_id": "integer required",
            "patch": "object required; event_name or due_date or due_time or time_precision",
        },
    ),
    CommandToolSpec(
        tool_name="create_source_recovery_proposal",
        target_kind="source",
        execution_boundary="proposal_or_ticket_chain",
        mutating=True,
        description="Create a source-recovery proposal for one source.",
        args_schema_hint={"source_id": "integer required"},
    ),
    CommandToolSpec(
        tool_name="create_family_relink_preview_proposal",
        target_kind="family",
        execution_boundary="proposal_or_ticket_chain",
        mutating=True,
        description="Create a family relink preview proposal.",
        args_schema_hint={"raw_type_id": "integer required", "family_id": "integer required"},
    ),
    CommandToolSpec(
        tool_name="create_family_relink_commit_proposal",
        target_kind="family",
        execution_boundary="proposal_or_ticket_chain",
        mutating=True,
        description="Create an executable family relink commit proposal.",
        args_schema_hint={"raw_type_id": "integer required", "family_id": "integer required"},
    ),
    CommandToolSpec(
        tool_name="create_label_learning_commit_proposal",
        target_kind="change",
        execution_boundary="proposal_or_ticket_chain",
        mutating=True,
        description="Create an executable label-learning add-alias proposal.",
        args_schema_hint={"change_id": "integer required", "family_id": "integer required"},
    ),
    CommandToolSpec(
        tool_name="create_approval_ticket",
        target_kind="proposal",
        execution_boundary="proposal_or_ticket_chain",
        mutating=True,
        description="Create an approval ticket from an executable proposal.",
        args_schema_hint={"proposal_id": "integer required or $ref", "channel": "string optional"},
    ),
    CommandToolSpec(
        tool_name="get_approval_ticket",
        target_kind="ticket",
        execution_boundary="read_only",
        mutating=False,
        description="Read an approval ticket.",
        args_schema_hint={"ticket_id": "string required or $ref"},
    ),
    CommandToolSpec(
        tool_name="confirm_approval_ticket",
        target_kind="ticket",
        execution_boundary="proposal_or_ticket_chain",
        mutating=True,
        description="Confirm and execute an approval ticket.",
        args_schema_hint={"ticket_id": "string required or $ref"},
    ),
    CommandToolSpec(
        tool_name="cancel_approval_ticket",
        target_kind="ticket",
        execution_boundary="proposal_or_ticket_chain",
        mutating=True,
        description="Cancel an open approval ticket.",
        args_schema_hint={"ticket_id": "string required or $ref"},
    ),
)


COMMAND_TOOL_SPEC_BY_NAME = {spec.tool_name: spec for spec in COMMAND_TOOL_SPECS}


def command_tool_spec(tool_name: str) -> CommandToolSpec:
    spec = COMMAND_TOOL_SPEC_BY_NAME.get(tool_name)
    if spec is None:
        raise KeyError(f"unknown command tool: {tool_name}")
    return spec


def command_tool_names() -> list[str]:
    return [spec.tool_name for spec in COMMAND_TOOL_SPECS]


def planner_tool_catalog() -> list[dict[str, object]]:
    return [spec.to_planner_dict() for spec in COMMAND_TOOL_SPECS]

