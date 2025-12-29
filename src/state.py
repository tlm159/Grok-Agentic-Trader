import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Portfolio:
    cash: float
    currency: str
    positions: dict = field(default_factory=dict)

    @staticmethod
    def _coerce_float(value, default):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def normalize_position(value):
        if isinstance(value, dict):
            qty = Portfolio._coerce_float(value.get("qty", 0.0), 0.0)
            return {
                "qty": qty,
                "sl": Portfolio._coerce_float(value.get("sl"), None),
                "tp": Portfolio._coerce_float(value.get("tp"), None),
                "avg_entry": Portfolio._coerce_float(value.get("avg_entry"), None),
            }
        if value is None:
            qty = 0.0
        else:
            qty = Portfolio._coerce_float(value, 0.0)
        return {"qty": qty, "sl": None, "tp": None, "avg_entry": None}

    @classmethod
    def load(cls, path, starting_cash, currency):
        state_path = Path(path)
        if state_path.exists():
            data = json.loads(state_path.read_text())
            positions_raw = data.get("positions", {})
            positions = {
                symbol: cls.normalize_position(value)
                for symbol, value in positions_raw.items()
            }
            return cls(
                cash=float(data.get("cash", starting_cash)),
                currency=data.get("currency", currency),
                positions=positions,
            )
        return cls(cash=float(starting_cash), currency=currency, positions={})

    def save(self, path):
        state_path = Path(path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cash": self.cash,
            "currency": self.currency,
            "positions": self.positions,
        }
        state_path.write_text(json.dumps(payload, indent=2))
