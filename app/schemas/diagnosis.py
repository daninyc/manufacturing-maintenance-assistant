from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    start_time: datetime | None = None
    end_time: datetime | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Time must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_time_range(self) -> "TimeRange":
        if self.start_time and self.end_time and self.start_time > self.end_time:
            raise ValueError("start_time must be earlier than end_time")
        return self


class DiagnoseRequest(TimeRange):
    equipment_id: str = Field(min_length=1, max_length=64)
    symptom: str = Field(min_length=1, max_length=2000)


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str
    source_type: Literal["knowledge", "alarm", "maintenance"]
    summary: str
    source_ref: str
    document_id: str | None = None
    policy_version: int | None = None
    content_version: str | None = None


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recommendation_id: str
    text: str
    evidence_ids: list[str] = Field(min_length=1)
    applicable_conditions: list[str] = Field(min_length=1)


class DiagnoseResponse(BaseModel):
    phenomenon: str
    evidence: list[Evidence]
    suggestions: list[str]
    recommendation_details: list[Recommendation] = Field(default_factory=list)
    conflict_evidence_ids: list[str] = Field(default_factory=list)
    risk_notice: str
    grounded: bool
    request_id: str = ""
    status: Literal["evidence_only", "insufficient_evidence", "human_review"] = "insufficient_evidence"
