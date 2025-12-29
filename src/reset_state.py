from config import load_config
from state import Portfolio


def main():
    config = load_config()
    state_path = config["paths"]["state_path"]
    portfolio = Portfolio(
        cash=float(config["trading"]["starting_cash"]),
        currency=config["trading"]["currency"],
        positions={},
    )
    portfolio.save(state_path)


if __name__ == "__main__":
    main()
