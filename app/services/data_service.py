"""Day 3 查询边界：返回稳定 JSON 包装，不调用检索或大模型。"""
import logging
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from app.core.config import DATABASE_PATH
from app.db.repositories import MaintenanceRepository
from app.db.session import DataAccessError
from app.schemas.maintenance import DataQuery


def query_data(payload: dict, *, path: Path = DATABASE_PATH) -> dict:
    request_id = str(uuid4())
    try:
        request = DataQuery.model_validate(payload)
    except ValidationError:
        return {"ok": False, "request_id": request_id, "code": "INPUT_ERROR",
                "message": "请检查操作、设备编号、limit（整数 1–50）与 severity"}
    repository = MaintenanceRepository(path, request_id=request_id)
    try:
        if request.operation == "equipment":
            data = repository.get_equipment(request.equipment_id).model_dump(mode="json")
        elif request.operation == "alarms":
            data = [row.model_dump(mode="json") for row in repository.list_recent_alarms(
                request.equipment_id, request.limit, request.severity)]
        else:
            data = [row.model_dump(mode="json") for row in repository.list_maintenance_history(
                request.equipment_id, request.limit)]
        return {"ok": True, "request_id": request_id, "data": data}
    except DataAccessError as exc:
        return {"ok": False, "request_id": request_id, "code": exc.code, "message": str(exc)}
    except ValidationError:
        logging.getLogger(__name__).error("code=DATA_INTEGRITY_ERROR request_id=%s", request_id)
        return {"ok": False, "request_id": request_id, "code": "DATA_INTEGRITY_ERROR",
                "message": "数据库记录不符合数据契约"}
