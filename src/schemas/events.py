"""Frozen v1 contracts for the parser and normalized session events."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .common import Actor, LogFormat, StepKind, ToolCallStatus


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRef(ContractModel):
    source_line: int = Field(ge=1)
    block_index: int = Field(ge=0)
    source_event_id: str | None = None
    source_message_id: str | None = None


class UsageRecord(ContractModel):
    """Usage of the original agent for one request, deduplicated by request_id."""

    request_id: str
    message_id: str | None = None
    model: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cache_creation_input_tokens: int | None = Field(default=None, ge=0)
    cache_read_input_tokens: int | None = Field(default=None, ge=0)
    source_lines: list[int] = Field(default_factory=list)
    step_ids: list[str] = Field(default_factory=list)
    is_final: bool | None = None
    warnings: list[str] = Field(default_factory=list)


class Step(ContractModel):
    """One normalized history item; a JSONL event may produce many Steps."""

    step_id: str
    session_id: str
    ordinal: int = Field(ge=0)
    source: SourceRef
    parent_event_id: str | None = None
    branch_id: str = "main"
    timestamp: datetime | None = None
    kind: StepKind
    actor: Actor
    tool_call_id: str | None = None
    tool_name: str | None = None
    arguments: dict[str, Any] | list[Any] | str | int | float | bool | None = None
    text: str | None = None
    text_truncated: bool = False
    is_error: bool | None = None
    usage_ref: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ToolCall(ContractModel):
    """A tool_use and its tool_result(s), matched by tool call ID."""

    tool_call_id: str
    call_step_id: str
    result_step_ids: list[str] = Field(default_factory=list)
    tool_name: str | None = None
    arguments: dict[str, Any] | list[Any] | str | int | float | bool | None = None
    status: ToolCallStatus = ToolCallStatus.UNKNOWN
    started_at: datetime | None = None
    finished_at: datetime | None = None
    unfinished: bool = True
    warnings: list[str] = Field(default_factory=list)


class ParseStats(ContractModel):
    total_lines: int = Field(default=0, ge=0)
    recognized_steps: int = Field(default=0, ge=0)
    invalid_lines: int = Field(default=0, ge=0)
    unknown_events: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)


class SessionInfo(ContractModel):
    session_id: str
    log_format: LogFormat = LogFormat.CLAUDE_CODE
    file_name: str | None = None
    source_session_ids: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    parser_version: str
    parse_stats: ParseStats
    limitations: list[str] = Field(default_factory=list)


class StepDetail(ContractModel):
    step: Step
    tool_call: ToolCall | None = None
    previous: list[Step] = Field(default_factory=list)
    following: list[Step] = Field(default_factory=list)
