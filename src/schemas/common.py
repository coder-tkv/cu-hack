"""Shared schema primitives.

The values in these enums are part of the frozen backend v1 contract.
"""

from enum import StrEnum


SCHEMA_VERSION = "v1"


class StepKind(StrEnum):
    HUMAN_MESSAGE = "human_message"
    ASSISTANT_TEXT = "assistant_text"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    SYSTEM_EVENT = "system_event"
    UNKNOWN = "unknown"


class Actor(StrEnum):
    HUMAN = "human"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class ToolCallStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    UNKNOWN = "unknown"


class AnalysisStatus(StrEnum):
    QUEUED = "queued"
    PARSING = "parsing"
    ANALYZING = "analyzing"
    EXPLAINING = "explaining"
    ASSEMBLING = "assembling"
    COMPLETE = "complete"
    PARTIAL = "partial"
    INSUFFICIENT_DATA = "insufficient_data"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


TERMINAL_STATUSES = frozenset(
    {
        AnalysisStatus.COMPLETE,
        AnalysisStatus.PARTIAL,
        AnalysisStatus.INSUFFICIENT_DATA,
        AnalysisStatus.FAILED,
        AnalysisStatus.INTERRUPTED,
    }
)
RUNNING_STATUSES = frozenset(
    {
        AnalysisStatus.PARSING,
        AnalysisStatus.ANALYZING,
        AnalysisStatus.EXPLAINING,
        AnalysisStatus.ASSEMBLING,
    }
)


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class LogFormat(StrEnum):
    CLAUDE_CODE = "claude_code"
