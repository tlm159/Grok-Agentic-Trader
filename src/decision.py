import json

ALLOWED_ACTIONS = {"BUY", "SELL", "HOLD"}


def parse_optional_price(value, label):
    if value is None:
        return None
    price = float(value)
    if price <= 0:
        raise ValueError(f"{label} must be positive")
    return price


def parse_optional_minutes(value):
    if value is None:
        raise ValueError("next_check_minutes is required")
    minutes = float(value)
    if minutes <= 0:
        raise ValueError("next_check_minutes must be positive")
    return minutes


def parse_decision(text):
    data = json.loads(text)
    action = str(data.get("action", "")).upper()
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"Unsupported action: {action}")

    symbol = data.get("symbol")
    notional = data.get("notional")
    reason = str(data.get("reason", ""))
    confidence = data.get("confidence")
    reflection = str(data.get("reflection", ""))
    sl_price = parse_optional_price(data.get("sl_price"), "sl_price")
    tp_price = parse_optional_price(data.get("tp_price"), "tp_price")
    next_check_minutes = parse_optional_minutes(data.get("next_check_minutes"))
    positions_ack = str(data.get("positions_ack", "")).upper()
    if positions_ack not in {"OPEN", "NONE"}:
        raise ValueError("positions_ack must be OPEN or NONE")
    positions_summary = str(data.get("positions_summary", ""))
    evidence = data.get("evidence", [])
    if not isinstance(evidence, list):
        evidence = []

    if action == "HOLD":
        hold_symbol = str(symbol).upper() if symbol else None
        return {
            "action": action,
            "symbol": hold_symbol,
            "notional": None,
            "reason": reason,
            "confidence": confidence,
            "reflection": reflection,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "next_check_minutes": next_check_minutes,
            "positions_ack": positions_ack,
            "positions_summary": positions_summary,
            "evidence": evidence,
        }

    if not symbol:
        raise ValueError("Missing symbol for trade action")
    if notional is None:
        raise ValueError("Missing notional for trade action")

    notional_value = float(notional)
    if notional_value <= 0:
        raise ValueError("Notional must be positive")

    return {
        "action": action,
        "symbol": str(symbol).upper(),
        "notional": notional_value,
        "reason": reason,
        "confidence": confidence,
        "reflection": reflection,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "next_check_minutes": next_check_minutes,
        "positions_ack": positions_ack,
        "positions_summary": positions_summary,
        "evidence": evidence,
    }
