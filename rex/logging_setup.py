"""Structured local logging without prompt or secret payloads."""

import json
import logging
from logging.handlers import RotatingFileHandler

from rex.config import PROJECT_ROOT


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "event": record.getMessage(),
        }, ensure_ascii=False)


def _logger():
    logger = logging.getLogger("rex")
    if not logger.handlers:
        directory = PROJECT_ROOT / "logs"
        directory.mkdir(exist_ok=True)
        handler = RotatingFileHandler(directory / "rex.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


log = _logger()