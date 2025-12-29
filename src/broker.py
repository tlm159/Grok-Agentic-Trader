from dataclasses import dataclass
from datetime import datetime, timezone

from state import Portfolio

@dataclass
class TradeResult:
    action: str
    symbol: str
    qty: float
    price: float
    notional: float
    timestamp: str


class PaperBroker:
    def __init__(self, allow_negative_cash=True, allow_short=True):
        self.allow_negative_cash = allow_negative_cash
        self.allow_short = allow_short

    @staticmethod
    def _get_position(portfolio, symbol):
        raw = portfolio.positions.get(symbol)
        return Portfolio.normalize_position(raw)

    @staticmethod
    def _set_position(portfolio, symbol, position):
        qty = float(position.get("qty", 0.0))
        if abs(qty) < 1e-8:
            portfolio.positions.pop(symbol, None)
            return
        portfolio.positions[symbol] = {
            "qty": qty,
            "sl": position.get("sl"),
            "tp": position.get("tp"),
            "avg_entry": position.get("avg_entry"),
        }

    def execute(self, action, symbol, notional, price, portfolio, sl_price=None, tp_price=None):
        if price <= 0:
            raise ValueError("Invalid price")
        qty = notional / price
        action_upper = action.upper()
        position = self._get_position(portfolio, symbol)
        current_qty = position["qty"]
        avg_entry = position.get("avg_entry")
        if action_upper == "BUY":
            if not self.allow_negative_cash and portfolio.cash < notional:
                notional = max(portfolio.cash, 0.0)
                qty = notional / price if price > 0 else 0.0
            portfolio.cash -= notional
            if current_qty >= 0:
                new_qty = current_qty + qty
                if new_qty > 0:
                    if avg_entry is None:
                        avg_entry = price
                    else:
                        avg_entry = (current_qty * avg_entry + qty * price) / new_qty
                position["qty"] = new_qty
                position["avg_entry"] = avg_entry
            else:
                cover_qty = min(qty, abs(current_qty))
                remaining_qty = current_qty + qty
                if remaining_qty < 0:
                    position["qty"] = remaining_qty
                elif remaining_qty == 0:
                    position["qty"] = 0.0
                    avg_entry = None
                else:
                    position["qty"] = remaining_qty
                    avg_entry = price
                position["avg_entry"] = avg_entry
            if sl_price is not None:
                position["sl"] = sl_price
            if tp_price is not None:
                position["tp"] = tp_price
            self._set_position(portfolio, symbol, position)
        elif action_upper == "SELL":
            if not self.allow_short:
                qty = min(qty, current_qty)
                notional = qty * price
            portfolio.cash += notional
            if current_qty <= 0:
                new_qty = current_qty - qty
                if avg_entry is None:
                    avg_entry = price
                else:
                    avg_entry = (abs(current_qty) * avg_entry + qty * price) / abs(new_qty)
                position["qty"] = new_qty
                position["avg_entry"] = avg_entry
            else:
                remaining_qty = current_qty - qty
                if remaining_qty > 0:
                    position["qty"] = remaining_qty
                elif remaining_qty == 0:
                    position["qty"] = 0.0
                    avg_entry = None
                else:
                    position["qty"] = remaining_qty
                    avg_entry = price
                position["avg_entry"] = avg_entry
            self._set_position(portfolio, symbol, position)
        else:
            raise ValueError(f"Unsupported action: {action}")
        timestamp = datetime.now(timezone.utc).isoformat()
        return TradeResult(
            action=action_upper,
            symbol=symbol,
            qty=qty,
            price=price,
            notional=notional,
            timestamp=timestamp,
        )
