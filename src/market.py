import yfinance as yf


def _extract_last_close(data):
    if data is None or data.empty or "Close" not in data:
        return None
    close = data["Close"].dropna()
    if close.empty:
        return None
    return float(close.iloc[-1])


def _get_intraday_price(ticker):
    for period, interval in (("1d", "1m"), ("5d", "5m")):
        try:
            data = ticker.history(period=period, interval=interval)
        except Exception:
            continue
        price = _extract_last_close(data)
        if price is not None:
            return price
    return None


def _get_recent_daily_close(ticker):
    try:
        data = ticker.history(period="5d", interval="1d")
    except Exception:
        return None
    return _extract_last_close(data)


def _get_current_price(ticker):
    # Prefer intraday data for live SL/TP checks, then fall back to the most recent daily close.
    intraday_price = _get_intraday_price(ticker)
    if intraday_price is not None:
        return intraday_price
    return _get_recent_daily_close(ticker)


def calculate_atr(data, period=14):
    """
    Calculate ATR (Average True Range) securely using pandas.
    Returns the last ATR value or None if insufficient data.
    """
    if len(data) < period + 1:
        return None

    high = data["High"]
    low = data["Low"]
    close = data["Close"]

    # Calculate TR (True Range)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()

    tr = tr1.combine(tr2, max).combine(tr3, max)

    # Using a simple rolling mean keeps the ATR stable and predictable.
    atr = tr.rolling(window=period).mean()

    return atr.iloc[-1]


def get_market_data(symbol):
    """
    Fetch comprehensive market data: current price, ATR, Volatility %.
    Used for safe decision making in V2.
    """
    ticker = yf.Ticker(symbol)
    current_price = _get_current_price(ticker)

    # Fetch daily candles for ATR calculation.
    try:
        data = ticker.history(period="1mo", interval="1d")
    except Exception:
        data = None

    if data is None or data.empty:
        if current_price is None:
            return None
        return {
            "price": current_price,
            "atr": None,
            "volatility_pct": None,
        }

    last_close = _extract_last_close(data)
    if current_price is None:
        current_price = last_close
    if current_price is None:
        return None

    # Calculate ATR (Volatility $)
    atr_value = calculate_atr(data, period=14)

    # Calculate Volatility % against the current tradable price when available.
    volatility_pct = (
        (atr_value / current_price)
        if atr_value is not None and current_price not in (None, 0)
        else None
    )

    return {
        "price": float(current_price),
        "atr": float(atr_value) if atr_value else None,
        "volatility_pct": float(volatility_pct) if volatility_pct else None,
    }


def get_last_price(symbol):
    data = get_market_data(symbol)
    return data["price"] if data else None
