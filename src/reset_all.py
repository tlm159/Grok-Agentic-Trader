from pathlib import Path

from config import load_config
from state import Portfolio


def main():
    config = load_config()
    state_path = config["paths"]["state_path"]
    trades_path = config["paths"]["trades_path"]
    dashboard_path = config["paths"].get("dashboard_path")
    loop_state_path = config["paths"].get("loop_state_path")
    live_search_cache = config.get("live_search", {}).get("cache_path")

    portfolio = Portfolio(
        cash=float(config["trading"]["starting_cash"]),
        currency=config["trading"]["currency"],
        positions={},
    )
    portfolio.save(state_path)

    Path(trades_path).parent.mkdir(parents=True, exist_ok=True)
    Path(trades_path).write_text("")

    if dashboard_path:
        Path(dashboard_path).parent.mkdir(parents=True, exist_ok=True)
        Path(dashboard_path).write_text("")

    if loop_state_path:
        Path(loop_state_path).parent.mkdir(parents=True, exist_ok=True)
        Path(loop_state_path).write_text("")

    if live_search_cache:
        Path(live_search_cache).parent.mkdir(parents=True, exist_ok=True)
        Path(live_search_cache).write_text("")


if __name__ == "__main__":
    main()
