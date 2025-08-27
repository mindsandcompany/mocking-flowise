import logging
import os
import sys
import json
from datetime import datetime, timezone
from typing import Any, Dict


class JsonFormatter(logging.Formatter):
    """Lightweight JSON log formatter without external deps."""

    def format(self, record: logging.LogRecord) -> str:
        base: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Attach caller info
        base["module"] = record.module
        base["funcName"] = record.funcName
        base["lineno"] = record.lineno

        # Merge extra fields (anything custom added via logger.*(..., extra={...}))
        for key, value in record.__dict__.items():
            if key in {
                "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
                "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
                "created", "msecs", "relativeCreated", "thread", "threadName", "processName",
                "process", "asctime"
            }:
                continue
            if key not in base:
                try:
                    json.dumps(value, ensure_ascii=False, default=str)
                    base[key] = value
                except Exception:
                    base[key] = str(value)

        # Exception text if present
        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(base, ensure_ascii=False, default=str)


def setup_logging() -> logging.Logger:
    """Configure root logger based on environment variables.

    ENV:
      - LOG_LEVEL: default INFO
      - LOG_FORMAT: "json" or "console" (default console)
    """
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    fmt = os.getenv("LOG_FORMAT", "console").lower()

    handler = logging.StreamHandler(stream=sys.stdout)

    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        # human-readable console format
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)

    logging.basicConfig(level=level, handlers=[handler], force=True)

    # Be respectful of uvicorn's loggers but inherit our level/handlers
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "gunicorn"):
        lg = logging.getLogger(name)
        lg.setLevel(level)

    return logging.getLogger()


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name) 