import json
from datetime import datetime, timezone
from pathlib import Path


def append_event(path, event):
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def append_run_log(path, message):
    if not path:
        return
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    line = f"[{timestamp}] {message}\n"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line)
