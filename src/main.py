import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from broker import PaperBroker
from config import load_config
from dashboard import load_decision_history, load_equity_series, write_dashboard
from decision import parse_decision
from llm import LLMClient
from log_utils import append_event, append_run_log
from live_search import LiveSearchUnavailable, fetch_live_context
from live_search_cache import is_cache_fresh, read_cache, write_cache
from market import get_market_data, get_last_price
from state import Portfolio
from alpaca_broker import AlpacaBroker
import os


def load_recent_events(path, limit=5):
    log_path = Path(path)
    if not log_path.exists():
        return []
    lines = log_path.read_text().splitlines()
    recent = []
    for line in lines[-limit:]:
        try:
            recent.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return recent


def load_last_events_by_type(path, event_type, limit=1):
    log_path = Path(path)
    if not log_path.exists():
        return []
    lines = log_path.read_text().splitlines()
    matches = []
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == event_type:
            matches.append(event)
            if len(matches) >= limit:
                break
    return matches


def build_market_snapshot(portfolio, watchlist=None):
    positions = {}
    price_by_symbol = {}
    positions_value = 0.0
    gross_exposure = 0.0
    open_pnl = 0.0
    for symbol, entry in portfolio.positions.items():
        normalized = Portfolio.normalize_position(entry)
        qty = normalized.get("qty", 0.0)
        sl_price = normalized.get("sl")
        tp_price = normalized.get("tp")
        avg_entry = normalized.get("avg_entry")
        # Use trusted price from Alpaca if available, else fetch
        cached_price = normalized.get("current_price")
        if cached_price is not None:
             price = cached_price
             price_by_symbol[symbol] = price
        else:
             price = get_last_price(symbol)
             price_by_symbol[symbol] = price

        if price is None:
            continue
            
        value = qty * price
        gross_exposure += abs(value)
        
        pnl = None
        pnl_pct = None
        
        # Use trusted PnL from Alpaca if available
        cached_pnl = normalized.get("unrealized_pl")
        
        if cached_pnl is not None:
             pnl = cached_pnl
             # Recalculate pct for display consistency
             basis = abs(float(avg_entry or price) * qty)
             if basis > 0:
                  pnl_pct = (pnl / basis) * 100
             open_pnl += pnl
        elif avg_entry is not None:
            pnl = (price - float(avg_entry)) * qty
            basis = abs(float(avg_entry) * qty)
            if basis > 0:
                pnl_pct = (pnl / basis) * 100
            open_pnl += pnl
        positions[symbol] = {
            "qty": qty,
            "price": price,
            "value": value,
            "sl": sl_price,
            "tp": tp_price,
            "avg_entry": avg_entry,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
        }
        positions_value += value
    
    # Use Broker-reported equity if available (e.g. from Alpaca), otherwise calculate estimate
    if portfolio.equity is not None:
         equity = portfolio.equity
    else:
         equity = portfolio.cash + positions_value
         
    leverage = None
    cash_ratio = None
    if equity > 0:
        leverage = gross_exposure / equity
        cash_ratio = portfolio.cash / equity
    watchlist_prices = {}
    if watchlist:
        for symbol in watchlist:
            if symbol in price_by_symbol:
                watchlist_prices[symbol] = price_by_symbol[symbol]
                continue
            market_data = get_market_data(symbol) or {}
            price = market_data.get("price")
            price_by_symbol[symbol] = price
            watchlist_prices[symbol] = market_data # Store FULL object (price, atr, volatility_pct)
    return {
        "positions": positions,
        "positions_value": positions_value,
        "equity": equity,
        "gross_exposure": gross_exposure,
        "net_exposure": positions_value,
        "leverage": leverage,
        "cash_ratio": cash_ratio,
        "open_pnl": open_pnl,
        "watchlist_prices": watchlist_prices,
    }


def build_positions_summary(portfolio):
    if not portfolio.positions:
        return "Aucune position ouverte."
    symbols = ", ".join(sorted(portfolio.positions.keys()))
    return f"Positions ouvertes: {symbols}."


def get_session_state():
    ny_tz = ZoneInfo("America/New_York")
    paris_tz = ZoneInfo("Europe/Paris")
    now_ny = datetime.now(ny_tz)
    open_ny = now_ny.replace(hour=9, minute=30, second=0, microsecond=0)
    # SAFETY: We set "close_ny" to 15:55 (5 mins before actual close)
    # This ensures "after_close" triggers whilst the market is still accepting orders.
    close_ny = now_ny.replace(hour=15, minute=55, second=0, microsecond=0)
    cutoff_ny = close_ny - timedelta(minutes=30)
    return {
        "now_ny": now_ny,
        "open_ny": open_ny,
        "close_ny": close_ny,
        "cutoff_ny": cutoff_ny,
        "open_paris": open_ny.astimezone(paris_tz),
        "close_paris": close_ny.astimezone(paris_tz),
        "cutoff_paris": cutoff_ny.astimezone(paris_tz),
        "is_weekend": now_ny.weekday() >= 5,
        "in_session": open_ny <= now_ny < close_ny,
        "in_cutoff": cutoff_ny <= now_ny < close_ny,
        "after_close": now_ny >= close_ny,
    }


def build_hold_decision(reason, positions_open, positions_summary, next_minutes, reflection=None):
    return {
        "action": "HOLD",
        "symbol": None,
        "notional": None,
        "reason": reason,
        "confidence": 0.5,
        "reflection": reflection or "Je reste en attente.",
        "sl_price": None,
        "tp_price": None,
        "next_check_minutes": next_minutes,
        "positions_ack": "OPEN" if positions_open else "NONE",
        "positions_summary": positions_summary,
        "evidence": [],
    }


def is_crypto_or_fx(symbol):
    if not symbol:
        return False
    upper = symbol.upper()
    return upper.endswith(("-USD", "-USDT", "-USDC")) or upper.endswith("=X")


def format_log_value(value, precision=4):
    if value is None:
        return "-"
    try:
        return f"{float(value):.{precision}f}"
    except (TypeError, ValueError):
        return "-"


def log_decision(run_log_path, decision, note=None):
    if not decision:
        return
    action = decision.get("action", "-")
    symbol = decision.get("symbol") or "-"
    notional = format_log_value(decision.get("notional"))
    reason = (decision.get("reason") or "-").replace("\n", " ").strip()
    extra = f" [{note}]" if note else ""
    append_run_log(
        run_log_path,
        f"Decision{extra}: {action} {symbol} notional={notional} reason={reason}",
    )


def log_trade(run_log_path, result, reason=None):
    if not result:
        return
    line = (
        f"Trade: {result.action} {result.symbol} qty={format_log_value(result.qty)} "
        f"price={format_log_value(result.price)} notional={format_log_value(result.notional)}"
    )
    if reason:
        line = f"{line} reason={reason}"
    append_run_log(run_log_path, line)


def list_exit_triggers(market_snapshot):
    triggers = []
    for symbol, info in market_snapshot["positions"].items():
        qty = info.get("qty", 0.0)
        price = info.get("price")
        if price is None or qty <= 0:
            continue
        sl_price = info.get("sl")
        tp_price = info.get("tp")
        if sl_price is not None and price <= sl_price:
            triggers.append(
                {
                    "symbol": symbol,
                    "qty": qty,
                    "price": price,
                    "trigger": "SL",
                    "sl": sl_price,
                    "tp": tp_price,
                }
            )
        elif tp_price is not None and price >= tp_price:
            triggers.append(
                {
                    "symbol": symbol,
                    "qty": qty,
                    "price": price,
                    "trigger": "TP",
                    "sl": sl_price,
                    "tp": tp_price,
                }
            )
    return triggers


def close_all_positions(portfolio, broker, trades_path, reason):
    last_trade = None
    for symbol, entry in list(portfolio.positions.items()):
        normalized = Portfolio.normalize_position(entry)
        qty = normalized.get("qty", 0.0)
        if abs(qty) < 1e-8:
            continue
        price = get_last_price(symbol)
        if price is None:
            append_event(
                trades_path,
                {
                    "type": "error",
                    "message": f"No price data for {symbol} during session close",
                    "symbol": symbol,
                },
            )
            continue
        action = "SELL" if qty > 0 else "BUY"
        notional = abs(qty) * price
        result = broker.execute(
            action=action,
            symbol=symbol,
            notional=notional,
            price=price,
            portfolio=portfolio,
        )
        last_trade = result
        append_event(
            trades_path,
            {
                "type": "session_close",
                "symbol": symbol,
                "qty": qty,
                "price": price,
                "reason": reason,
            },
        )
        append_event(
            trades_path,
            {
                "type": "trade",
                "result": {
                    "action": result.action,
                    "symbol": result.symbol,
                    "qty": result.qty,
                    "price": result.price,
                    "notional": result.notional,
                    "timestamp": result.timestamp,
                },
                "reason": reason,
                "confidence": None,
            },
        )
    return last_trade


def build_system_prompt():
    return (
        "SYSTEM INSTRUCTION: EXECUTE AUTONOMOUS INTRADAY TRADING STRATEGY.\n"
        "OBJECTIVE: Maximize Risk-Adjusted Returns by analyzing News Sentiment and Market Volatility (ATR).\n"
        "\n"
        "DECISION FRAMEWORK (Chain of Thought):\n"
        "1. DATA INGESTION: Analyze 'Live context' (News) & 'Market snapshot' (Price, ATR).\n"
        "2. SIGNAL GENERATION: Identify correlation between News Sentiment and Price Action. "
        "   - Positive News + Bullish Price = BUY Signal.\n"
        "   - Ambiguous Data = HOLD Signal.\n"
        "3. RISK COMPUTATION: Calculate Position Size based on conviction and Volatility (ATR).\n"
        "   - YOU have full authority over position sizing. You may split capital across multiple assets (Diversification).\n"
        "   - MANDATORY: Define Stop Loss (SL) based on ATR (e.g., Price - 1.5 * ATR).\n"
        "   - EXIT AUTONOMY: You can SELL at any time (Profit Taking / Conviction Change). You are NOT bound to wait for SL/TP triggers.\n"
        "4. EXECUTION: Generate JSON Order.\n"
        "\n"
        "CONSTRAINTS (Technical & Hard):\n"
        "- UNIVERSE: You are authorized to trade ANY US-listed ticker found in 'Live context'. You are NOT restricted to a fixed watchlist.\n"
        "- SHORT SELLING: DISABLED (Technical limitation). Do NOT attempt to Short.\n"
        "- TIME LIMIT: All positions forcefully closed at 15:55 NY. No overnight holds.\n"
        "- HALLUCINATIONS: You must NOT invent prices or ATR. Use only provided data.\n"
        "\n"
        "OUTPUT SCHEMA (JSON Only):\n"
        "{ \n"
        "  \"action\": \"BUY|SELL|HOLD\", \n"
        "  \"symbol\": \"TICKER\", \n"
        "  \"notional\": 15.0, \n"
        "  \"reason\": \"Brief rationale in French\", \n"
        "  \"confidence\": 0.9, \n"
        "  \"reflection\": \"Step-by-step Chain of Thought analysis in French (Data->Signal->Risk)\", \n"
        "  \"sl_price\": 100.50, \n"
        "  \"tp_price\": 105.00, \n"
        "  \"evidence\": [\"News source\", \"ATR value\"] \n"
        "} \n"
        "Note: 'SELL' is ONLY for closing existing Long positions. To open a trade, use 'BUY'.\n"
        "To adjust SL/TP without trading, use action 'HOLD' with the symbol and the new 'sl_price'."
    )


def build_user_prompt(
    portfolio,
    recent_events,
    market_snapshot,
    equity_delta,
    starting_cash,
    live_context,
    allowed_symbols,
    symbol_rules,
    decision_memory,
    fixed_minutes,
):
    return (
        "Portfolio:\n"
        f"Cash: {portfolio.cash} {portfolio.currency}\n"
        f"Buying Power: {getattr(portfolio, 'buying_power', portfolio.cash)} {portfolio.currency}\n"
        f"Positions: {json.dumps(portfolio.positions)}\n\n"
        "Market snapshot:\n"
        f"{json.dumps(market_snapshot)}\n\n"
        "Portfolio metrics:\n"
        f"Equity: {market_snapshot.get('equity')}\n"
        f"Gross exposure: {market_snapshot.get('gross_exposure')}\n"
        f"Net exposure: {market_snapshot.get('net_exposure')}\n"
        f"Leverage: {market_snapshot.get('leverage')}\n"
        f"Cash ratio: {market_snapshot.get('cash_ratio')}\n\n"
        f"Equity change since last snapshot: {json.dumps(equity_delta)}\n\n"
        f"Starting cash budget: {starting_cash} {portfolio.currency}\n\n"
        f"Live context:\n{live_context}\n\n"
        "Decision memory:\n"
        f"{json.dumps(decision_memory)}\n\n"
        "Recent events:\n"
        f"{json.dumps(recent_events)}\n\n"
        f"Allowed symbols: {', '.join(allowed_symbols) if allowed_symbols else 'any'}.\n"
        f"Symbol rules: {symbol_rules or 'none'}.\n"
        "Decide your next action using the allowed symbols and symbol rules only.\n"
        "Refer to the SYSTEM INSTRUCTION for the required JSON Output Schema (Chain of Thought).\n"
        f"Set next_check_minutes to {fixed_minutes} (system uses a fixed schedule).\n"
    )


def request_decision(
    llm,
    system_prompt,
    user_prompt,
    trades_path,
    positions_open,
    positions_summary_default,
):
    raw = llm.decide(system_prompt, user_prompt)
    append_event(trades_path, {"type": "decision", "raw": raw, "attempt": 1})
    try:
        decision = parse_decision(raw)
    except Exception as exc:
        message = str(exc)
        append_event(
            trades_path,
            {
                "type": "decision_error",
                "message": message,
                "raw": raw,
                "attempt": 1,
            },
        )
        fallback = {
            "action": "HOLD",
            "symbol": None,
            "notional": None,
            "reason": f"Decision invalide: {message}",
            "confidence": 0.0,
            "reflection": "Je reste en attente.",
            "sl_price": None,
            "tp_price": None,
            "next_check_minutes": None,
            "positions_ack": "OPEN" if positions_open else "NONE",
            "positions_summary": positions_summary_default,
            "evidence": [],
        }
        append_event(
            trades_path, {"type": "decision_fallback", "decision": fallback}
        )
        return raw, fallback

    desired_ack = "OPEN" if positions_open else "NONE"
    corrected = False
    if decision.get("positions_ack") != desired_ack:
        decision["positions_ack"] = desired_ack
        corrected = True
    if not decision.get("positions_summary"):
        decision["positions_summary"] = positions_summary_default
        corrected = True
    if decision.get("action") == "BUY" and decision.get("sl_price") is None:
        message = "sl_price is required for BUY (Safety First)"
        append_event(
            trades_path,
            {
                "type": "decision_error",
                "message": message,
                "raw": raw,
                "attempt": 1,
            },
        )
        fallback = {
            "action": "HOLD",
            "symbol": None,
            "notional": None,
            "reason": "Decision invalide: SL/TP manquant pour un BUY.",
            "confidence": 0.0,
            "reflection": "Je reste en attente.",
            "sl_price": None,
            "tp_price": None,
            "next_check_minutes": None,
            "positions_ack": desired_ack,
            "positions_summary": positions_summary_default,
            "evidence": [],
        }
        append_event(
            trades_path, {"type": "decision_fallback", "decision": fallback}
        )
        return raw, fallback

    if corrected:
        append_event(
            trades_path, {"type": "decision_corrected", "decision": decision}
        )
    append_event(
        trades_path,
        {"type": "decision_parsed", "decision": decision, "attempt": 1},
    )
    return raw, decision


def build_dashboard_payload(
    config,
    portfolio,
    market_snapshot,
    equity,
    equity_delta,
    decision,
    raw,
    prompt,
    trade,
    error,
    equity_series,
    decision_history,
):
    return {
        "model": config["llm"]["model"],
        "currency": portfolio.currency,
        "cash": portfolio.cash,
        "starting_cash": float(config["trading"]["starting_cash"]),
        "positions": market_snapshot["positions"],
        "positions_value": market_snapshot["positions_value"],
        "equity": equity,
        "gross_exposure": market_snapshot.get("gross_exposure"),
        "net_exposure": market_snapshot.get("net_exposure"),
        "leverage": market_snapshot.get("leverage"),
        "cash_ratio": market_snapshot.get("cash_ratio"),
        "open_pnl": market_snapshot.get("open_pnl"),
        "equity_delta": equity_delta,
        "decision": decision,
        "raw": raw,
        "prompt": prompt,
        "trade": trade,
        "error": error,
        "equity_series": equity_series,
        "decision_history": decision_history,
        "next_check_minutes": decision.get("next_check_minutes") if decision else None,
        "positions_summary": decision.get("positions_summary") if decision else None,
    }


def main():
    load_dotenv()
    config = load_config()
    state_path = config["paths"]["state_path"]
    trades_path = config["paths"]["trades_path"]
    dashboard_path = config["paths"]["dashboard_path"]
    run_log_path = config["paths"].get("run_log_path")
    
    # Init Broker
    broker_type = config["trading"].get("broker", "paper")
    alpaca_broker = None
    if broker_type == "alpaca":
        api_key = os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("ALPACA_SECRET_KEY")
        endpoint = os.getenv("ALPACA_ENDPOINT", "https://paper-api.alpaca.markets")
        paper_mode = "paper" in endpoint
        if not api_key or not secret_key:
             raise ValueError("Alpaca broker selected but keys missing in .env")
        alpaca_broker = AlpacaBroker(api_key, secret_key, paper=paper_mode)

    allowed_symbols = [symbol.upper() for symbol in config["trading"].get("universe", [])]
    watchlist_symbols = config["trading"].get("watchlist", []) or allowed_symbols
    watchlist_symbols = [symbol.upper() for symbol in watchlist_symbols]
    symbol_rules = config["trading"].get("symbol_rules")

    # Check if fresh start
    is_fresh_start = not os.path.exists(state_path)

    portfolio = Portfolio.load(
        state_path,
        starting_cash=config["trading"]["starting_cash"],
        currency=config["trading"]["currency"],
    )

    if alpaca_broker:
        portfolio = alpaca_broker.sync_portfolio(portfolio)
        
        # AUTO-UPDATE CONFIG IF FRESH START
        # If we have no history, we align the "starting point" with reality to have clean PnL
        if is_fresh_start and abs(portfolio.cash - config["trading"]["starting_cash"]) > 0.01:
            print(f"✨ First Run Auto-Config: Updating starting_cash from {config['trading']['starting_cash']} to {portfolio.cash}")
            config["trading"]["starting_cash"] = portfolio.cash
            
            # Save to settings.json
            try:
                with open("config/settings.json", "w") as f:
                    json.dump(config, f, indent=2)
            except Exception as e:
                print(f"⚠️ Failed to auto-update settings.json: {e}")

        portfolio.save(state_path)

    last_equity_events = load_last_events_by_type(trades_path, "equity", limit=1)
    last_equity = last_equity_events[0] if last_equity_events else None
    market_snapshot = build_market_snapshot(portfolio, watchlist=watchlist_symbols)
    equity = market_snapshot["equity"]
    equity_delta = None
    if last_equity and last_equity.get("equity") is not None:
        equity_delta = equity - float(last_equity["equity"])
    append_event(
        trades_path,
        {
            "type": "equity",
            "equity": equity,
            "cash": portfolio.cash,
            "positions_value": market_snapshot["positions_value"],
        },
    )
    equity_series = load_equity_series(trades_path, limit=200)

    exit_triggers = list_exit_triggers(market_snapshot)
    if exit_triggers:
        broker = PaperBroker(
            allow_negative_cash=config["trading"]["allow_negative_cash"],
            allow_short=config["trading"]["allow_short"],
        )
        if alpaca_broker:
             # For auto-exit, we use the abstract execute method or specific logic?
             # Auto-exits in main.py loops through triggers and calls execute.
             # We can make `broker` variable point to alpaca_broker wrapper.
             pass
        
        # Abstract broker interface for exit loop
        active_broker = alpaca_broker if alpaca_broker else broker
        
        last_trade = None
        for trigger in exit_triggers:
            notional = trigger["qty"] * trigger["price"]
            result = active_broker.execute(
                action="SELL",
                symbol=trigger["symbol"],
                notional=notional,
                price=trigger["price"],
                portfolio=portfolio,
            )
            last_trade = result
            append_event(
                trades_path,
                {
                    "type": "auto_exit",
                    "symbol": trigger["symbol"],
                    "qty": trigger["qty"],
                    "price": trigger["price"],
                    "trigger": trigger["trigger"],
                    "sl": trigger["sl"],
                    "tp": trigger["tp"],
                },
            )
            append_event(
                trades_path,
                {
                    "type": "trade",
                    "result": {
                        "action": result.action,
                        "symbol": result.symbol,
                        "qty": result.qty,
                        "price": result.price,
                        "notional": result.notional,
                        "timestamp": result.timestamp,
                    },
                    "reason": f"AUTO_EXIT_{trigger['trigger']}",
                    "confidence": None,
                },
            )
            log_trade(run_log_path, result, reason="AUTO_EXIT")
        
        if alpaca_broker:
            portfolio = alpaca_broker.sync_portfolio(portfolio)
            
        portfolio.save(state_path)
        market_snapshot = build_market_snapshot(portfolio, watchlist=watchlist_symbols)
        equity = market_snapshot["equity"]
        append_event(
            trades_path,
            {
                "type": "equity",
                "equity": equity,
                "cash": portfolio.cash,
                "positions_value": market_snapshot["positions_value"],
            },
        )
        equity_series = load_equity_series(trades_path, limit=200)
        decision_history = load_decision_history(trades_path, limit=12)
        decision = {
            "action": "SELL",
            "symbol": last_trade.symbol if last_trade else None,
            "notional": last_trade.notional if last_trade else None,
            "reason": "Auto exit triggered by SL/TP",
            "confidence": None,
            "reflection": "Auto exit executed from the prior plan.",
            "sl_price": None,
            "tp_price": None,
        }
        log_decision(run_log_path, decision, note="AUTO_EXIT")
        dashboard_payload = build_dashboard_payload(
            config=config,
            portfolio=portfolio,
            market_snapshot=market_snapshot,
            equity=equity,
            equity_delta=equity_delta,
            decision=decision,
            raw=None,
            prompt=None,
            trade={
                "action": last_trade.action,
                "symbol": last_trade.symbol,
                "qty": last_trade.qty,
                "price": last_trade.price,
                "notional": last_trade.notional,
                "timestamp": last_trade.timestamp,
            }
            if last_trade
            else None,
            error=None,
            equity_series=equity_series,
            decision_history=decision_history,
        )
        write_dashboard(dashboard_path, dashboard_payload)
        return

    session = get_session_state()
    positions_open = len(portfolio.positions) > 0
    positions_summary_default = build_positions_summary(portfolio)
    fixed_next_minutes = config["trading"].get("cycle_minutes", 60)

    if session["after_close"] and positions_open and not session["is_weekend"]:
        broker = PaperBroker(
            allow_negative_cash=config["trading"]["allow_negative_cash"],
            allow_short=config["trading"]["allow_short"],
        )
        active_broker = alpaca_broker if alpaca_broker else broker
        
        if alpaca_broker:
             alpaca_broker.close_all_positions()
             last_trade = None
             portfolio = alpaca_broker.sync_portfolio(portfolio)
        else:
             reason = "SESSION_CLOSE"
             last_trade = close_all_positions(portfolio, broker, trades_path, reason)
             log_trade(run_log_path, last_trade, reason=reason)
        
        portfolio.save(state_path)
        market_snapshot = build_market_snapshot(portfolio, watchlist=watchlist_symbols)
        equity = market_snapshot["equity"]
        append_event(
            trades_path,
            {
                "type": "equity",
                "equity": equity,
                "cash": portfolio.cash,
                "positions_value": market_snapshot["positions_value"],
            },
        )
        equity_series = load_equity_series(trades_path, limit=200)
        decision = {
            "action": "SELL",
            "symbol": last_trade.symbol if last_trade else None,
            "notional": last_trade.notional if last_trade else None,
            "reason": "Clôture de session NY : positions fermées par sécurité.",
            "confidence": None,
            "reflection": "Clôture automatique à 22h (heure FR).",
            "sl_price": None,
            "tp_price": None,
            "next_check_minutes": fixed_next_minutes,
            "positions_ack": "NONE",
            "positions_summary": "Aucune position ouverte.",
            "evidence": [],
        }
        log_decision(run_log_path, decision, note="SESSION_CLOSE")
        append_event(
            trades_path, {"type": "decision_parsed", "decision": decision, "attempt": 0}
        )
        decision_history = load_decision_history(trades_path, limit=12)
        dashboard_payload = build_dashboard_payload(
            config=config,
            portfolio=portfolio,
            market_snapshot=market_snapshot,
            equity=equity,
            equity_delta=equity_delta,
            decision=decision,
            raw=None,
            prompt=None,
            trade={
                "action": last_trade.action,
                "symbol": last_trade.symbol,
                "qty": last_trade.qty,
                "price": last_trade.price,
                "notional": last_trade.notional,
                "timestamp": last_trade.timestamp,
            }
            if last_trade
            else None,
            error=None,
            equity_series=equity_series,
            decision_history=decision_history,
        )
        write_dashboard(dashboard_path, dashboard_payload)
        return

    if session["is_weekend"]:
        decision = build_hold_decision(
            "Week-end : marchés US fermés.",
            positions_open,
            positions_summary_default,
            fixed_next_minutes,
            reflection=positions_summary_default,
        )
        log_decision(run_log_path, decision, note="WEEKEND")
        append_event(
            trades_path, {"type": "decision_parsed", "decision": decision, "attempt": 0}
        )
        decision_history = load_decision_history(trades_path, limit=12)
        dashboard_payload = build_dashboard_payload(
            config=config,
            portfolio=portfolio,
            market_snapshot=market_snapshot,
            equity=equity,
            equity_delta=equity_delta,
            decision=decision,
            raw=None,
            prompt=None,
            trade=None,
            error=None,
            equity_series=equity_series,
            decision_history=decision_history,
        )
        write_dashboard(dashboard_path, dashboard_payload)
        return

    if session["in_cutoff"]:
        cutoff = session["cutoff_paris"].strftime("%H:%M")
        decision = build_hold_decision(
            f"Fenêtre de clôture : pas de nouvelle position après {cutoff} (heure FR).",
            positions_open,
            positions_summary_default,
            fixed_next_minutes,
            reflection=positions_summary_default,
        )
        log_decision(run_log_path, decision, note="CUTOFF")
        append_event(
            trades_path, {"type": "decision_parsed", "decision": decision, "attempt": 0}
        )
        decision_history = load_decision_history(trades_path, limit=12)
        dashboard_payload = build_dashboard_payload(
            config=config,
            portfolio=portfolio,
            market_snapshot=market_snapshot,
            equity=equity,
            equity_delta=equity_delta,
            decision=decision,
            raw=None,
            prompt=None,
            trade=None,
            error=None,
            equity_series=equity_series,
            decision_history=decision_history,
        )
        write_dashboard(dashboard_path, dashboard_payload)
        return

    if not session["in_session"]:
        open_time = session["open_paris"].strftime("%H:%M")
        close_time = session["close_paris"].strftime("%H:%M")
        decision = build_hold_decision(
            f"Hors session NY ({open_time}–{close_time} heure FR).",
            positions_open,
            positions_summary_default,
            fixed_next_minutes,
            reflection="En attente de l'ouverture du marché (15h30).",
        )
        log_decision(run_log_path, decision, note="OUT_OF_SESSION")
        append_event(
            trades_path, {"type": "decision_parsed", "decision": decision, "attempt": 0}
        )
        decision_history = load_decision_history(trades_path, limit=12)
        dashboard_payload = build_dashboard_payload(
            config=config,
            portfolio=portfolio,
            market_snapshot=market_snapshot,
            equity=equity,
            equity_delta=equity_delta,
            decision=decision,
            raw=None,
            prompt=None,
            trade=None,
            error=None,
            equity_series=equity_series,
            decision_history=decision_history,
        )
        write_dashboard(dashboard_path, dashboard_payload)
        return

    live_context = "none"
    live_search_cfg = config.get("live_search", {})
    if live_search_cfg.get("enabled"):
        cache_path = live_search_cfg.get("cache_path", "data/live_search_cache.json")
        cooldown_minutes = live_search_cfg.get("cooldown_minutes", 60)
        cached = read_cache(cache_path)
        if is_cache_fresh(cached, cooldown_minutes):
            live_context = cached.get("context", "none")
            append_event(trades_path, {"type": "live_search_cache_hit"})
        else:
            queries = live_search_cfg.get("queries")
            if not queries:
                queries = [live_search_cfg.get("query", "")]
            max_queries = live_search_cfg.get("max_queries_per_run", len(queries))
            queries = list(queries)[: max(1, int(max_queries))]
            try:
                contexts = []
                for idx, query in enumerate(queries, start=1):
                    context = fetch_live_context(
                        query=query,
                        model=live_search_cfg.get("model", config["llm"]["model"]),
                        max_sources=live_search_cfg.get("max_sources"),
                    )
                    contexts.append(f"[Query {idx}] {query}\n{context}")
                live_context = "\n\n".join(contexts)
                write_cache(cache_path, live_context, queries)
                append_event(trades_path, {"type": "live_search_cache_write"})
            except LiveSearchUnavailable as exc:
                live_context = "unavailable"
                if cached and cached.get("context"):
                    live_context = cached.get("context")
                    append_event(
                        trades_path,
                        {"type": "live_search_fallback_cache", "message": str(exc)},
                    )
                else:
                    append_event(
                        trades_path, {"type": "live_search_error", "message": str(exc)}
                    )

    # DYNAMIC WATCHLIST: Extract tickers from news to fetch their prices
    if live_context and live_context != "none":
        # Rough regex for tickers (2-5 uppercase letters)
        potential_tickers = set(re.findall(r'\b[A-Z]{2,5}\b', live_context))
        # Basic stopwords to avoid fetching price for "THE", "AND", etc.
        stopwords = {"THE", "AND", "FOR", "THAT", "WITH", "THIS", "FROM", "HAVE", "ARE", "NOT", "BUT", "ALL", "WHO", "WHAT", "WHEN", "WHERE", "WHY", "HOW", "CAN", "YOU", "YOUR", "THEY", "THEIR", "OUR", "WE", "SHE", "HE", "IT", "IS", "AM", "ARE", "WAS", "WERE", "BE", "BEEN", "BEING", "HAS", "HAD", "DO", "DOES", "DID", "JONES", "DOW", "NASDAQ", "NYSE", "AMEX", "ETF", "USD", "EUR", "GBP", "AUD", "CAD", "JPY", "CNY", "HKD", "CHF", "SEK", "NZD", "KRW", "SGD", "NOK", "MXN", "INR", "RUB", "ZAR", "TRY", "BRL", "TWD", "DKK", "PLN", "THB", "IDR", "HUF", "CZK", "ILS", "CLP", "PHP", "AED", "COP", "SAR", "MYR", "RON"}
        
        dynamic_tickers = [t for t in potential_tickers if t not in stopwords]
        
        if dynamic_tickers:
            # Append to watchlist (deduplicated)
            old_count = len(watchlist_symbols)
            watchlist_symbols = list(set(watchlist_symbols + dynamic_tickers))
            new_count = len(watchlist_symbols)
            
            if new_count > old_count:
                # RE-BUILD Snapshot to fetch prices for these new tickers
                append_event(trades_path, {"type": "dynamic_watchlist", "added": dynamic_tickers})
                market_snapshot = build_market_snapshot(portfolio, watchlist=watchlist_symbols)
                equity = market_snapshot["equity"]

    recent_events = load_recent_events(trades_path, limit=5)
    system_prompt = build_system_prompt()
    decision_memory = load_decision_history(trades_path, limit=6)
    user_prompt = build_user_prompt(
        portfolio,
        recent_events,
        market_snapshot,
        equity_delta,
        config["trading"]["starting_cash"],
        live_context,
        allowed_symbols,
        symbol_rules,
        decision_memory,
        fixed_next_minutes,
    )
    prompt_payload = {"system": system_prompt, "user": user_prompt}
    append_event(trades_path, {"type": "prompt", "prompt": prompt_payload})

    llm = LLMClient(
        base_url=config["llm"]["base_url"],
        model=config["llm"]["model"],
        temperature=config["llm"]["temperature"],
    )

    raw, decision = request_decision(
        llm,
        system_prompt,
        user_prompt,
        trades_path,
        positions_open=positions_open,
        positions_summary_default=positions_summary_default,
    )
    decision["next_check_minutes"] = fixed_next_minutes
    log_decision(run_log_path, decision, note="LLM")

    if decision["action"] == "HOLD":
        updated_position = False
        if decision.get("symbol") and (
            decision.get("sl_price") is not None or decision.get("tp_price") is not None
        ):
            symbol = decision["symbol"]
            if symbol in portfolio.positions:
                position = Portfolio.normalize_position(portfolio.positions.get(symbol))
                if decision.get("sl_price") is not None:
                    position["sl"] = decision["sl_price"]
                if decision.get("tp_price") is not None:
                    position["tp"] = decision["tp_price"]
                portfolio.positions[symbol] = position
                portfolio.save(state_path)
                append_event(
                    trades_path,
                    {
                        "type": "sl_tp_update",
                        "symbol": symbol,
                        "sl": position.get("sl"),
                        "tp": position.get("tp"),
                    },
                )
                updated_position = True
            else:
                append_event(
                    trades_path,
                    {
                        "type": "error",
                        "message": f"Cannot update SL/TP for missing position: {symbol}",
                        "symbol": symbol,
                    },
                )
        if updated_position:
            market_snapshot = build_market_snapshot(portfolio, watchlist=watchlist_symbols)
            equity = market_snapshot["equity"]
        decision_history = load_decision_history(trades_path, limit=12)
        dashboard_payload = build_dashboard_payload(
            config=config,
            portfolio=portfolio,
            market_snapshot=market_snapshot,
            equity=equity,
            equity_delta=equity_delta,
            decision=decision,
            raw=raw,
            prompt=prompt_payload,
            trade=None,
            error=None,
            equity_series=equity_series,
            decision_history=decision_history,
        )
        write_dashboard(dashboard_path, dashboard_payload)
        return

    if allowed_symbols:
        symbol = decision["symbol"]
        if symbol not in allowed_symbols and symbol not in portfolio.positions:
            append_event(
                trades_path,
                {
                    "type": "error",
                    "message": f"Symbol not allowed: {symbol}",
                    "symbol": symbol,
                },
            )
            decision_history = load_decision_history(trades_path, limit=12)
            dashboard_payload = build_dashboard_payload(
                config=config,
                portfolio=portfolio,
                market_snapshot=market_snapshot,
                equity=equity,
                equity_delta=equity_delta,
                decision=decision,
                raw=raw,
                prompt=prompt_payload,
                trade=None,
                error=f"Symbol not allowed: {symbol}",
                equity_series=equity_series,
                decision_history=decision_history,
            )
            write_dashboard(dashboard_path, dashboard_payload)
            return

    symbol = decision["symbol"]
    notional = decision["notional"]

    if is_crypto_or_fx(symbol):
        append_event(
            trades_path,
            {
                "type": "error",
                "message": f"Crypto/FX symbol blocked: {symbol}",
                "symbol": symbol,
            },
        )
        log_decision(run_log_path, decision, note="BLOCKED_SYMBOL")
        decision_history = load_decision_history(trades_path, limit=12)
        dashboard_payload = build_dashboard_payload(
            config=config,
            portfolio=portfolio,
            market_snapshot=market_snapshot,
            equity=equity,
            equity_delta=equity_delta,
            decision=decision,
            raw=raw,
            prompt=prompt_payload,
            trade=None,
            error=f"Crypto/FX symbol blocked: {symbol}",
            equity_series=equity_series,
            decision_history=decision_history,
        )
        write_dashboard(dashboard_path, dashboard_payload)
        return

    price = get_last_price(symbol)
    if price is None:
        append_event(
            trades_path,
            {
                "type": "error",
                "message": f"No price data for {symbol}",
                "symbol": symbol,
            },
        )
        dashboard_payload = build_dashboard_payload(
            config=config,
            portfolio=portfolio,
            market_snapshot=market_snapshot,
            equity=equity,
            equity_delta=equity_delta,
            decision=decision,
            raw=raw,
            prompt=prompt_payload,
            trade=None,
            error=f"No price data for {symbol}",
            equity_series=equity_series,
            decision_history=load_decision_history(trades_path, limit=12),
        )
        write_dashboard(dashboard_path, dashboard_payload)
        return

    broker = PaperBroker(
        allow_negative_cash=config["trading"]["allow_negative_cash"],
        allow_short=config["trading"]["allow_short"],
    )
    active_broker = alpaca_broker if alpaca_broker else broker

    result = active_broker.execute(
        action=decision["action"],
        symbol=symbol,
        notional=notional,
        price=price,
        portfolio=portfolio,
        sl_price=decision.get("sl_price"),
        tp_price=decision.get("tp_price"),
    )
    
    if alpaca_broker:
        portfolio = alpaca_broker.sync_portfolio(portfolio)
    log_trade(run_log_path, result, reason=decision.get("reason"))

    portfolio.save(state_path)
    append_event(
        trades_path,
        {
            "type": "trade",
            "result": {
                "action": result.action,
                "symbol": result.symbol,
                "qty": result.qty,
                "price": result.price,
                "notional": result.notional,
                "timestamp": result.timestamp,
            },
            "reason": decision.get("reason"),
            "confidence": decision.get("confidence"),
        },
    )

    market_snapshot = build_market_snapshot(portfolio, watchlist=watchlist_symbols)
    equity = market_snapshot["equity"]
    dashboard_payload = build_dashboard_payload(
        config=config,
        portfolio=portfolio,
        market_snapshot=market_snapshot,
        equity=equity,
        equity_delta=equity_delta,
        decision=decision,
        raw=raw,
        prompt=prompt_payload,
        trade={
            "action": result.action,
            "symbol": result.symbol,
            "qty": result.qty,
            "price": result.price,
            "notional": result.notional,
            "timestamp": result.timestamp,
        },
        error=None,
        equity_series=equity_series,
        decision_history=load_decision_history(trades_path, limit=12),
    )
    write_dashboard(dashboard_path, dashboard_payload)


if __name__ == "__main__":
    main()
