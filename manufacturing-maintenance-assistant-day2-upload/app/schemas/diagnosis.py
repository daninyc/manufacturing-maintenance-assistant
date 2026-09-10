from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class DiagnoseRequest(BaseModel):
    equipment_id: str = Field(min_length=1, max_length=64)
    symptom: str = Field(min_length=1, max_length=2000)
    start_time: datetime | None = None
    end_time: datetime | None = None

    @model_validator(mode="after")
    def validate_time_range(self) -> "DiagnoseRequest":
        if self.start_time and self.end_time and self.start_time > self.end_time:
            raise ValueError("start_time must be earlier than end_time")
        return self


class Evidence(BaseModel):
    evidence_id: str
    source_type: Literal["knowledge", "alarm", "maintenance"]
    summary: str
    source_ref: str


class DiagnoseResponse(BaseModel):
    phenomenon: str
    evidence: list[Evidence]
    suggestions: list[str]
    risk_notice: str
    grounded: bool

