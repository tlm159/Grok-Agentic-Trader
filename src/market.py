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
