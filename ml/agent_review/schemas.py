"""Version 2: code owns facts and text; the model selects cited facts/advice."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Evidence(StrictModel):
    step_id: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=100)
    text: str = Field(max_length=6000)
    source_line: int | None = Field(default=None, ge=1)

class Fact(StrictModel):
    fact_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=2000)
    evidence_step_ids: list[str] = Field(min_length=1, max_length=40)

class ObservedAlternative(StrictModel):
    alternative_id: str = Field(min_length=1, max_length=200)
    tool_name: str = Field(min_length=1, max_length=100)
    evidence_step_ids: list[str] = Field(min_length=2, max_length=4)

class Candidate(StrictModel):
    candidate_id: str = Field(min_length=1, max_length=200)
    kind: Literal["explicit_tool_error", "repeated_tool_call", "read_many_files"]
    priority: Literal["high", "medium", "low"] = "low"
    task_context: str | None = Field(default=None, max_length=6000)
    facts: list[Fact] = Field(min_length=1, max_length=30)
    evidence: list[Evidence] = Field(min_length=1, max_length=50)
    alternatives: list[ObservedAlternative] = Field(default_factory=list, max_length=5)
    # Backend must assert this only for an episode with all necessary evidence.
    context_complete: bool = False
    limitations: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def check_references(self):
        steps = [s.step_id for s in self.evidence]
        facts = [f.fact_id for f in self.facts]
        alternatives = [a.alternative_id for a in self.alternatives]
        if any(len(ids) != len(set(ids)) for ids in (steps, facts, alternatives)):
            raise ValueError("Duplicate evidence, fact or alternative ID")
        for item in [*self.facts, *self.alternatives]:
            refs = item.evidence_step_ids
            if len(refs) != len(set(refs)) or not set(refs) <= set(steps):
                raise ValueError("Fact/alternative references missing or duplicate evidence")
        return self

class ReviewInput(StrictModel):
    schema_version: Literal["2"] = "2"
    source_id: str = Field(min_length=1, max_length=200)
    task: str | None = Field(default=None, max_length=6000)
    candidates: list[Candidate] = Field(default_factory=list, max_length=1000)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_candidates(self):
        ids = [c.candidate_id for c in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate candidate_id")
        return self

class Citation(StrictModel):
    step_id: str
    quote: str

Advice = Literal["none", "inspect_failure", "change_approach", "narrow_read_scope", "reuse_observed_tool"]

class ModelDecision(StrictModel):
    # No unrestricted prose: the model cannot invent a problem, cause or utility.
    candidate_id: str
    assessment: Literal["inefficient", "reasonable", "uncertain"]
    fact_ids: list[str]
    citations: list[Citation]
    advice: Advice
    alternative_id: str | None

class Judgment(StrictModel):
    candidate_id: str
    assessment: Literal["inefficient", "reasonable", "uncertain"]
    fact_ids: list[str]
    evidence_step_ids: list[str]
    citations: list[Citation]
    explanation: str
    likely_cause: None = None
    action: str | None
    verification: str | None
    rule_text: str | None
    advice: Advice
    alternative_id: str | None
    limitations: list[str]

class CompressionStats(StrictModel):
    original_input_bytes: int = Field(ge=0)
    compressed_input_bytes: int = Field(ge=0)
    saved_input_bytes: int = Field(ge=0)
    reused_texts: int = Field(ge=0)
    evidence_steps: int = Field(ge=0)

class ReviewedCandidate(StrictModel):
    candidate: Candidate
    compression: CompressionStats | None = None
    judgment: Judgment | None = None
    error: str | None = None

class ReviewReport(StrictModel):
    schema_version: Literal["2"] = "2"
    source_id: str
    status: Literal["complete", "partial", "no_candidates"]
    model: str
    prompt_version: str
    candidates_total: int
    candidates_reviewed: int
    api_calls: int
    analysis_usage: dict[str, int]
    findings: list[ReviewedCandidate]
    warnings: list[str]
