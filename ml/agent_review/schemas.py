"""Backend -> ML -> backend contracts. IDs must point to real evidence."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(StrictModel):
    step_id: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=100)
    text: str = Field(max_length=6000)
    source_line: int | None = Field(default=None, ge=1)


class Candidate(StrictModel):
    candidate_id: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=100)
    facts: list[str] = Field(min_length=1, max_length=30)
    evidence: list[Evidence] = Field(min_length=1, max_length=50)
    limitations: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def unique_steps(self):
        ids = [step.step_id for step in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate evidence step_id within candidate")
        return self


class ReviewInput(StrictModel):
    schema_version: Literal["1"] = "1"
    source_id: str = Field(min_length=1, max_length=200)
    task: str | None = Field(default=None, max_length=6000)
    candidates: list[Candidate] = Field(default_factory=list, max_length=1000)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_candidates(self):
        ids = [item.candidate_id for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate candidate_id")
        return self


class Judgment(StrictModel):
    # All fields required, nullable where appropriate, for Structured Outputs.
    candidate_id: str
    assessment: Literal["inefficient", "reasonable", "uncertain"]
    evidence_step_ids: list[str]
    explanation: str
    likely_cause: str | None
    action: str | None
    verification: str | None
    rule_text: str | None
    limitations: list[str]


class ReviewedCandidate(StrictModel):
    candidate: Candidate
    judgment: Judgment | None = None
    error: str | None = None


class ReviewReport(StrictModel):
    schema_version: Literal["1"] = "1"
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
