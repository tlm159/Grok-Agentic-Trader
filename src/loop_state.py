import json
from datetime import datetime, timezone
from pathlib import Path


def read_next_check_minutes(path):
    loop_path = Path(path)
    if not loop_path.exists():
        return None
    try:
        data = json.loads(loop_path.read_text())
    except json.JSONDecodeError:
        return None
    value = data.get("next_check_minutes")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def write_next_check_minutes(path, minutes):
    loop_path = Path(path)
    loop_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "next_check_minutes": minutes,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    loop_path.write_text(json.dumps(payload, indent=2))
