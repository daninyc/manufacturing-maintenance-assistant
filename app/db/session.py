"""只读会话和数据库错误边界；写连接仅由离线种子脚本创建。"""
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.db.models import APPLICATION_ID, SCHEMA_VERSION

logger = logging.getLogger(__name__)


class DataAccessError(RuntimeError):
    def __init__(self, code: str, message: str, request_id: str):
        super().__init__(message)
        self.code = code
        self.request_id = request_id


def database_error(exc: sqlite3.Error, request_id: str) -> DataAccessError:
    number = getattr(exc, "sqlite_errorcode", 0) & 0xFF
    busy = number in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
    code = "DATABASE_BUSY" if busy else "DATABASE_ERROR"
    # 不记录 SQL 参数和整份资料；request_id 用于连接用户输出与错误日志。
    logger.error("code=%s request_id=%s sqlite_code=%s", code, request_id, number)
    message = "数据库被占用，请关闭写事务后重试" if busy else "数据库读取或结构异常，请核对数据库文件"
    return DataAccessError(code, message, request_id)


@contextmanager
def read_connection(path: Path, request_id: str):
    if not path.is_file():
        logger.error("code=DATABASE_NOT_FOUND request_id=%s", request_id)
        raise DataAccessError("DATABASE_NOT_FOUND", "数据库不存在，请先运行 scripts.seed_db", request_id)
    connection = None
    try:
        # as_uri 转义路径中的 ?/#；mode=ro 不会悄悄新建缺失文件。
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        identity = connection.execute("PRAGMA application_id").fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if (identity, version) != (APPLICATION_ID, SCHEMA_VERSION):
            logger.error("code=DATABASE_SCHEMA_ERROR request_id=%s", request_id)
            raise DataAccessError("DATABASE_SCHEMA_ERROR", "数据库不是当前项目支持的版本", request_id)
        yield connection
    except sqlite3.Error as exc:
        raise database_error(exc, request_id) from exc
    finally:
        if connection is not None:
            connection.close()
