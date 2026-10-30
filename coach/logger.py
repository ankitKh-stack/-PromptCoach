"""Appends one JSON line per completed session."""
import json
from datetime import datetime, timezone
from pathlib import Path

from coach.config import path


def log_session(record: dict, log_file: Path | None = None) -> None:
    log_file = log_file or path("log_file")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), **record}
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
