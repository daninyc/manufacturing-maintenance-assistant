"""Day 3 输入与 DTO；不把数据库连接或 sqlite3.Row 暴露给调用者。"""
from datetime import date, datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Text = Annotated[str, Field(min_length=1, max_length=2000)]
Identifier = Annotated[str, Field(min_length=1, max_length=64)]
Severity = Literal["info", "warning", "critical"]


class EquipmentLookup(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    equipment_id: Identifier


class RecordQuery(EquipmentLookup):
    # strict=True：拒绝布尔值、小数和字符串，避免调用者绕过 CLI 校验。
    limit: int = Field(default=5, ge=1, le=50, strict=True)
    severity: Severity | None = None


class DataQuery(RecordQuery):
    operation: Literal["equipment", "alarms", "maintenance"]

    @model_validator(mode="after")
    def check_filter(self) -> "DataQuery":
        if self.severity is not None and self.operation != "alarms":
            raise ValueError("severity 仅用于报警查询")
        return self


class Equipment(EquipmentLookup):
    name: Text
    model: Identifier
    equipment_type: Identifier
    production_line: Identifier
    status: Literal["active", "offline", "maintenance"]
    installation_date: date
    source_type: Literal["simulation"] = "simulation"


class Alarm(EquipmentLookup):
    alarm_id: Identifier
    code: Identifier
    severity: Severity
    message: Text
    occurred_at: datetime
    acknowledged: bool
    resolved: bool
    document_id: Identifier
    source_type: Literal["simulation"] = "simulation"

    @field_validator("occurred_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("报警时间必须携带时区")
        return value.astimezone(timezone.utc)


class MaintenanceRecord(EquipmentLookup):
    record_id: Identifier
    symptom: Text
    action: Text
    result: Literal["resolved", "unresolved", "escalated"]
    maintained_at: datetime
    document_id: Identifier
    source_type: Literal["simulation"] = "simulation"

    @field_validator("maintained_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("维修时间必须携带时区")
        return value.astimezone(timezone.utc)


class SeedDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_type: Literal["self_authored_simulation"]
    version: Literal["day3-v1"]
    description: str
    equipment: list[Equipment] = Field(min_length=1)
    alarms: list[Alarm]
    maintenance_records: list[MaintenanceRecord]

    @model_validator(mode="after")
    def validate_relations(self) -> "SeedDataset":
        for rows, key in [(self.equipment, "equipment_id"), (self.alarms, "alarm_id"),
                          (self.maintenance_records, "record_id")]:
            ids = [getattr(row, key) for row in rows]
            if len(ids) != len(set(ids)):
                raise ValueError(f"种子数据存在重复 {key}")
        equipment = {row.equipment_id: row for row in self.equipment}
        for row in [*self.alarms, *self.maintenance_records]:
            if row.equipment_id not in equipment:
                raise ValueError("子记录引用未知设备")
            moment = row.occurred_at if isinstance(row, Alarm) else row.maintained_at
            if moment.date() < equipment[row.equipment_id].installation_date:
                raise ValueError("记录时间早于设备安装日期")
        return self
