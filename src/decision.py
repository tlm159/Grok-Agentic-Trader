import json

ALLOWED_ACTIONS = {"BUY", "SELL", "HOLD"}


def _strip_code_fences(text):
    if "```" not in text:
        return text
    parts = text.split("```")
    if len(parts) < 3:
        return text
    block = parts[1]
    lines = block.splitlines()
    if lines and lines[0].strip().lower() == "json":
        return "\n".join(lines[1:]).strip()
    return block.strip()


def _extract_json_object(text):
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _repair_json(text):
    if not text:
        return text
    candidate = text.replace(",}", "}").replace(",]", "]")
    open_brackets = candidate.count("[")
    close_brackets = candidate.count("]")
    if close_brackets < open_brackets and candidate.endswith("}"):
        candidate = candidate[:-1] + ("]" * (open_brackets - close_brackets)) + "}"
    return candidate


def _safe_json_load(text):
    cleaned = _strip_code_fences(text).strip()
    candidates = [cleaned]
    extracted = _extract_json_object(cleaned)
    if extracted and extracted != cleaned:
        candidates.append(extracted)
    for candidate in list(candidates):
        repaired = _repair_json(candidate)
        if repaired and repaired not in candidates:
            candidates.append(repaired)
    last_error = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise ValueError("Invalid JSON")


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
    data = _safe_json_load(text)
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
    
    # Optional legacy fields (relaxed for V2)
    positions_ack = str(data.get("positions_ack", "NONE")).upper()
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
