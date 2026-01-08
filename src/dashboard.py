import json
from datetime import datetime, timezone
from pathlib import Path


def load_equity_series(trades_path, limit=200):
    log_path = Path(trades_path)
    if not log_path.exists():
        return []
    lines = log_path.read_text().splitlines()
    series = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "equity":
            continue
        series.append(
            {
                "timestamp": event.get("timestamp"),
                "equity": event.get("equity"),
            }
        )
    if limit is None:
        return series
    return series[-limit:]


def load_decision_history(trades_path, limit=12):
    log_path = Path(trades_path)
    if not log_path.exists():
        return []
    lines = log_path.read_text().splitlines()
    history = []
    skip_next_parsed = False
    seen = set()
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_type = event.get("type")
        if event_type == "decision_adjusted":
            skip_next_parsed = True
            continue
        if event_type == "decision_parsed":
            if skip_next_parsed:
                skip_next_parsed = False
                continue
        elif event_type not in {"decision_fallback", "decision_corrected"}:
            continue
        decision = event.get("decision", {})
        
        # Deduplication: Key based on timestamp, action, symbol
        key = (event.get("timestamp"), decision.get("action"), decision.get("symbol"))
        if key in seen:
            continue
        seen.add(key)

        history.append(
            {
                "timestamp": event.get("timestamp"),
                "action": decision.get("action"),
                "symbol": decision.get("symbol"),
                "notional": decision.get("notional"),
                "reason": decision.get("reason"),
                "confidence": decision.get("confidence"),
                "reflection": decision.get("reflection"),
                "sl_price": decision.get("sl_price"),
                "tp_price": decision.get("tp_price"),
                "positions_summary": decision.get("positions_summary"),
                "evidence": decision.get("evidence"),
            }
        )
        if len(history) >= limit:
            break
    return list(reversed(history))


def write_dashboard(path, payload):
    dashboard_path = Path(path)
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(payload)
    data.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    dashboard_path.write_text(json.dumps(data, indent=2))
