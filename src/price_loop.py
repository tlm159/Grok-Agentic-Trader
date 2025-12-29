import json
import time
from datetime import datetime, timezone
from pathlib import Path

from config import load_config
from dashboard import load_decision_history
from main import build_market_snapshot
from state import Portfolio


def read_dashboard(path):
    dashboard_path = Path(path)
    if not dashboard_path.exists():
        return {}
    try:
        return json.loads(dashboard_path.read_text())
    except json.JSONDecodeError:
        return {}


def update_equity_series(series, equity, timestamp, limit=200):
    if not isinstance(series, list):
        series = []
    series.append({"timestamp": timestamp, "equity": equity})
    return series[-limit:]


def write_dashboard(path, payload):
    dashboard_path = Path(path)
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    dashboard_path.write_text(json.dumps(payload, indent=2))


def refresh_dashboard(config):
    state_path = config["paths"]["state_path"]
    trades_path = config["paths"]["trades_path"]
    dashboard_path = config["paths"]["dashboard_path"]
    allowed_symbols = [symbol.upper() for symbol in config["trading"].get("universe", [])]

    portfolio = Portfolio.load(
        state_path,
        starting_cash=config["trading"]["starting_cash"],
        currency=config["trading"]["currency"],
    )

    market_snapshot = build_market_snapshot(portfolio, watchlist=allowed_symbols)
    equity = market_snapshot["equity"]
    timestamp = datetime.now(timezone.utc).isoformat()

    last_dashboard = read_dashboard(dashboard_path)
    equity_delta = None
    if last_dashboard.get("equity") is not None:
        equity_delta = equity - float(last_dashboard["equity"])

    equity_series = update_equity_series(
        last_dashboard.get("equity_series"), equity, timestamp
    )

    decision_history = load_decision_history(trades_path, limit=12)
    if not decision_history:
        cached_history = last_dashboard.get("decision_history")
        if isinstance(cached_history, list) and cached_history:
            decision_history = cached_history

    payload = {
        "timestamp": timestamp,
        "model": last_dashboard.get("model", config["llm"]["model"]),
        "currency": portfolio.currency,
        "cash": portfolio.cash,
        "starting_cash": float(config["trading"]["starting_cash"]),
        "positions": market_snapshot["positions"],
        "positions_value": market_snapshot["positions_value"],
        "equity": equity,
        "equity_delta": equity_delta,
        "gross_exposure": market_snapshot.get("gross_exposure"),
        "net_exposure": market_snapshot.get("net_exposure"),
        "leverage": market_snapshot.get("leverage"),
        "cash_ratio": market_snapshot.get("cash_ratio"),
        "open_pnl": market_snapshot.get("open_pnl"),
        "decision": last_dashboard.get("decision"),
        "raw": last_dashboard.get("raw"),
        "prompt": last_dashboard.get("prompt"),
        "trade": last_dashboard.get("trade"),
        "error": last_dashboard.get("error"),
        "equity_series": equity_series,
        "decision_history": decision_history,
        "next_check_minutes": last_dashboard.get("next_check_minutes"),
        "positions_summary": last_dashboard.get("positions_summary"),
    }

    write_dashboard(dashboard_path, payload)


def run_loop():
    config = load_config()
    refresh_seconds = config["trading"].get("price_refresh_seconds", 10)
    refresh_seconds = max(2, float(refresh_seconds))

    while True:
        try:
            refresh_dashboard(config)
        except Exception as exc:
            print(f"Price loop error: {exc}")
        time.sleep(refresh_seconds)


if __name__ == "__main__":
    run_loop()
