import math
from datetime import datetime, timezone
from ib_insync import *
from state import Portfolio
from broker import TradeResult
import time

class IbkrBroker:
    def __init__(self, host='127.0.0.1', port=4002, client_id=1, account=''):
        """
        Initializes the IBKR Broker connection.
        """
        self.ib = IB()
        self.host = host
        self.port = port
        self.client_id = client_id
        self.account = account # Optional: Specify account ID if multiple
        
        print(f"🔌 IBKR: Connecting to {self.host}:{self.port}...")
        try:
            self.ib.connect(self.host, self.port, clientId=self.client_id)
            print("✅ IBKR: Connected!")
            
            # Switch to 'Real-Time' market data type if available, or 'Frozen' if market closed
            self.ib.reqMarketDataType(3)  # 3 = Delayed (Free), 1 = Live (Paid) - adjusting to Delayed to save costs for now?
            # User has 100 EUR, likely no subscription. Delayed is safer default.
            
        except Exception as e:
            print(f"❌ IBKR: Connexion Failed: {e}")
            raise RuntimeError(f"IBKR Connection Failed. check Gateway. Error: {e}")

    def is_connected(self):
        """Returns True if connected to IB Gateway."""
        return self.ib.isConnected()

    def sync_portfolio(self, portfolio: Portfolio):
        """
        Syncs local portfolio with IBKR Account.
        """
        try:
            # 1. Sync Cash & Equity
            # tags: 'TotalCashValue' (Liquidity), 'SettledCash' (T+1 Safety), 'BuyingPower', 'NetLiquidation' (Equity)
            summary = self.ib.accountSummary()
            
            total_cash = 0.0
            buying_power = 0.0
            equity = 0.0
            settled_cash = 0.0
            currency = "USD" # Default
            
            for item in summary:
                if item.tag == 'TotalCashValue':
                    total_cash = float(item.value)
                    currency = item.currency
                elif item.tag == 'BuyingPower':
                    buying_power = float(item.value)
                elif item.tag == 'NetLiquidation':
                    equity = float(item.value)
                elif item.tag == 'SettledCash':
                    settled_cash = float(item.value)

            portfolio.cash = total_cash
            portfolio.buying_power = buying_power
            portfolio.equity = equity
            portfolio.currency = currency
            portfolio.settled_cash = settled_cash

            # 2. Sync Positions
            positions = self.ib.positions()
            new_positions = {}
            
            for p in positions:
                symbol = p.contract.symbol
                qty = float(p.position)
                avg_entry = float(p.avgCost)
                
                if qty == 0:
                    continue
                    
                # Get current price ? 
                # Ideally we ask market data, but for sync speed we might fallback 
                # to passed portfolio price or 0 if not available.
                # For accurate PL, we need price.
                # Let's try to keep it fast. Main loop has prices.
                current_price = 0.0 # Placeholder
                if symbol in portfolio.positions:
                     current_price = portfolio.positions[symbol].get("current_price", 0.0)

                # Preserves SL/TP logic from main memory
                existing_sl = None
                existing_tp = None
                if symbol in portfolio.positions:
                   norm = Portfolio.normalize_position(portfolio.positions[symbol])
                   existing_sl = norm.get("sl")
                   existing_tp = norm.get("tp")

                new_positions[symbol] = {
                    "qty": qty,
                    "avg_entry": avg_entry,
                    "current_price": current_price,
                    "unrealized_pl": (current_price - avg_entry) * qty if current_price else 0.0,
                    "sl": existing_sl,
                    "tp": existing_tp
                }
            
            portfolio.positions = new_positions
            return portfolio

        except Exception as e:
            print(f"❌ IBKR Sync Error: {e}")
            return portfolio

    def get_settled_cash(self):
        """
        Fetches the REAL 'SettledCash' to prevent GFV.
        """
        summary = self.ib.accountSummary()
        for item in summary:
            if item.tag == 'SettledCash':
                return float(item.value)
        return 0.0

    def execute(self, action, symbol, notional, price, portfolio, sl_price=None, tp_price=None):
        """
        Executes orders on IBKR with GFV Guard.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        action = action.upper()

        # 1. HOLD Logic
        if action == "HOLD":
            if symbol in portfolio.positions:
                pos = portfolio.positions[symbol]
                if sl_price is not None: pos["sl"] = sl_price
                if tp_price is not None: pos["tp"] = tp_price
            return TradeResult("HOLD", symbol, 0, price, 0, timestamp)

        # 2. SELL Logic
        if action == "SELL":
            if symbol not in portfolio.positions:
                print(f"⚠️ IBKR SAFETY: Blocked SELL on {symbol} (No Position).")
                return TradeResult("BLOCKED", symbol, 0, price, 0, timestamp)

            qty_to_close = portfolio.positions[symbol]["qty"]
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            
            order = MarketOrder('SELL', qty_to_close)
            trade = self.ib.placeOrder(contract, order)
            
            # Wait for fill? Or Fire & Forget? 
            # We return a result assuming success, next sync_portfolio will confirm.
            return TradeResult("SELL", symbol, qty_to_close, price, notional, timestamp)

        # 3. BUY Logic (With GFV Guard)
        if action == "BUY":
            # GFV CHECK 🛡️
            settled_cash = self.get_settled_cash()
            # If notional > settled_cash, we are using unsettled funds -> GFV RISK if sold today.
            # Strict Rule: NEVER buy with more than settled cash.
            if notional > settled_cash:
                print(f"🛡️ GFV GUARD: Blocked BUY {symbol} (${notional}). Only ${settled_cash} Settled Cash available.")
                return TradeResult("BLOCKED_GFV", symbol, 0, price, 0, timestamp)

            # Quantity Calculation
            # IBKR often prefers Share Qty. 
            qty = math.floor(notional / price) # Safer to floor to avoid "Insufficient funds" rounding
            if qty < 1:
                print(f"⚠️ Ignored BUY {symbol}: Notional ${notional} insufficient for 1 share at ${price}.")
                return TradeResult("IGNORED_SMALL", symbol, 0, price, 0, timestamp)

            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            
            order = MarketOrder('BUY', qty)
            trade = self.ib.placeOrder(contract, order)
            
            return TradeResult("BUY", symbol, qty, price, notional, timestamp)

        return TradeResult("UNKNOWN", symbol, 0, price, 0, timestamp)

    def close_all_positions(self):
        """
        Panic Close / End of Day.
        """
        print("🚨 IBKR: Closing ALL positions...")
        positions = self.ib.positions()
        for p in positions:
            contract = p.contract
            self.ib.qualifyContracts(contract)
            qty = p.position
            if qty > 0:
                order = MarketOrder('SELL', qty)
                self.ib.placeOrder(contract, order)
                print(f" -> Closing {contract.symbol} ({qty})")
        print("✅ IBKR: All close orders sent.")

