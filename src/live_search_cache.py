import json
from datetime import datetime, timezone
from pathlib import Path


def read_cache(path):
    cache_path = Path(path)
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text())
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def is_cache_fresh(cache, cooldown_minutes):
    if not cache:
        return False
    timestamp = cache.get("timestamp")
    if not timestamp:
        return False
    try:
        ts = datetime.fromisoformat(timestamp)
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - ts).total_seconds()
    return age_seconds < float(cooldown_minutes) * 60


def write_cache(path, context, queries):
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    existing = None
    if cache_path.exists():
        try:
            existing = json.loads(cache_path.read_text())
        except json.JSONDecodeError:
            existing = None
    history = []
    if isinstance(existing, dict):
        history = existing.get("history", [])
        if not isinstance(history, list):
            history = []
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "context": context,
        "queries": queries,
    }
    history.append(entry)
    history = history[-5:]
    payload = {
        "timestamp": entry["timestamp"],
        "context": context,
        "queries": queries,
        "history": history,
    }
    cache_path.write_text(json.dumps(payload, indent=2))
