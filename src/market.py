import yfinance as yf


def get_last_price(symbol):
    ticker = yf.Ticker(symbol)
    data = ticker.history(period="1d", interval="1m")
    if data.empty:
        data = ticker.history(period="5d", interval="1d")
    if data.empty:
        return None
    close = data["Close"].dropna()
    if close.empty:
        return None
    return float(close.iloc[-1])

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
    
    # Calculate ATR (Simple Rolling Mean often used, or Wilder's Smoothing)
    # Using simple rolling mean for robustness/simplicity in V2
    atr = tr.rolling(window=period).mean()
    
    return atr.iloc[-1]


def get_market_data(symbol):
    """
    Fetch comprehensive market data: Price, ATR, Volatility %.
    Used for safe decision making in V2.
    """
    ticker = yf.Ticker(symbol)
    
    # Fetch 1 month of Daily data for ATR calculation
    data = ticker.history(period="1mo", interval="1d")
    
    if data.empty:
        return None
        
    last_close = float(data["Close"].iloc[-1])
    
    # Calculate ATR (Volatility $)
    atr_value = calculate_atr(data, period=14)
    
    # Calculate Volatility % (ATR / Price)
    volatility_pct = (atr_value / last_close) if atr_value else None
    
    return {
        "price": last_close,
        "atr": float(atr_value) if atr_value else None,
        "volatility_pct": float(volatility_pct) if volatility_pct else None
    }


def get_last_price(symbol):
    # Legacy wrapper for backward compatibility
    data = get_market_data(symbol)
    return data["price"] if data else None
