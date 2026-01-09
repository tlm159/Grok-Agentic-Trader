import os
from datetime import datetime, timezone
from dataclasses import dataclass
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from state import Portfolio
from broker import TradeResult

class AlpacaBroker:
    def __init__(self, key_id, secret_key, paper=True):
        self.client = TradingClient(key_id, secret_key, paper=paper)
        print(f"🦙 Alpaca: Connected ({'Paper' if paper else 'Live'})")

    def is_connected(self):
        """Check if Alpaca API is reachable."""
        try:
            self.client.get_account()
            return True
        except Exception:
            return False

    def get_day_trade_count(self):
        """
        Returns the number of day trades in the last 5 business days.
        Uses Alpaca's account.daytrade_count field.
        """
        try:
            account = self.client.get_account()
            return int(account.daytrade_count)
        except Exception as e:
            print(f"⚠️ Could not get day trade count: {e}")
            return 0  # Assume 0 if error (safer to allow trading)

    def can_day_trade(self):
        """
        Returns True if we can still day trade (count < 3).
        PDT rule: Max 3 day trades per 5 business days for accounts < $25k.
        """
        count = self.get_day_trade_count()
        can_trade = count < 3
        if not can_trade:
            print(f"🛑 PDT GUARD: Day trade count = {count}/3. Cannot open intraday positions!")
        return can_trade

    def sync_portfolio(self, portfolio: Portfolio):
        """
        Syncs the local portfolio state with Alpaca's account state.
        Updates cash and positions.
        """
        try:
            # Sync Cash & Equity
            account = self.client.get_account()
            # CRITICAL: Distinguish Cash (Net Value) from Buying Power (Trading limit)
            portfolio.cash = float(account.cash)
            portfolio.buying_power = float(account.buying_power)
            portfolio.currency = account.currency
            portfolio.equity = float(account.equity)

            # Sync Positions
            alpaca_positions = self.client.get_all_positions()
            new_positions = {}
            
            for p in alpaca_positions:
                symbol = p.symbol
                qty = float(p.qty)
                market_value = float(p.market_value)
                avg_entry = float(p.avg_entry_price)
                current_price = float(p.current_price)
                unrealized_pl = float(p.unrealized_pl)
                
                # Retrieve existing SL/TP and open_date from local state if available
                existing_sl = None
                existing_tp = None
                existing_open_date = None
                if symbol in portfolio.positions:
                    norm = Portfolio.normalize_position(portfolio.positions[symbol])
                    existing_sl = norm.get("sl")
                    existing_tp = norm.get("tp")
                    existing_open_date = norm.get("open_date")

                new_positions[symbol] = {
                    "qty": qty,
                    "sl": existing_sl,
                    "tp": existing_tp,
                    "avg_entry": avg_entry,
                    "current_price": current_price,
                    "unrealized_pl": unrealized_pl,
                    "open_date": existing_open_date,  # Preserve open date for PDT guard
                }
            
            portfolio.positions = new_positions
            return portfolio
        except Exception as e:
            print(f"Error syncing with Alpaca: {e}")
            return portfolio

    def execute(self, action, symbol, notional, price, portfolio, sl_price=None, tp_price=None):
        """
        Executes an order on Alpaca.
        Note: logic differs slightly from PaperBroker. We send the order, then sync.
        """
        if action.upper() == "HOLD":
            # Just update local SL/TP if provided
            # Since we sync with Alpaca, we need to persist these changes in the portfolio object passed
            # However, sync_portfolio overrides positions.
            # We need a mechanism to PERSIST SL/TP across syncs.
            # In sync_portfolio (line 35), we already try to preserve existing SL/TP.
            # So here we just update the portfolio object.
            if symbol in portfolio.positions:
                pos = portfolio.positions[symbol]
                if sl_price is not None:
                    pos["sl"] = sl_price
                if tp_price is not None:
                    pos["tp"] = tp_price
            
            timestamp = datetime.now(timezone.utc).isoformat()
            return TradeResult("HOLD", symbol, 0, price, 0, timestamp)

        if action.upper() == "SELL":
            # SAFETY GUARD 1: Prevent opening Short positions if no position exists
            if symbol not in portfolio.positions:
                print(f"⚠️ SAFETY: Blocked SELL on {symbol} (No Position). Preventing Accidental Short.")
                timestamp = datetime.now(timezone.utc).isoformat()
                return TradeResult("BLOCKED", symbol, 0, price, 0, timestamp)
            
            # SAFETY GUARD 2: Prevent same-day sells (PDT rule)
            pos = portfolio.positions[symbol]
            open_date = pos.get("open_date") if isinstance(pos, dict) else None
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            
            if open_date == today_str:
                print(f"🛑 SAME-DAY GUARD: Blocked SELL {symbol}. Position opened today ({open_date}). Wait until tomorrow.")
                timestamp = datetime.now(timezone.utc).isoformat()
                return TradeResult("BLOCKED_SAME_DAY", symbol, 0, price, 0, timestamp)

            side = OrderSide.SELL
        else:
            # Swing Trading Mode: No PDT guard needed (we never sell same day)
            side = OrderSide.BUY
        
        # Prepare order data
        # Alpaca allows notional orders for fractional shares
        # FIX: Round notional to 2 decimals to avoid "notional value must be limited to 2 decimal places"
        if notional is not None:
            notional = round(notional, 2)
            
        req = MarketOrderRequest(
            symbol=symbol,
            notional=notional if side == OrderSide.BUY else None,
            qty=None if side == OrderSide.BUY else (notional / price), # For sell, we might need qty if notional not supported for sell? Alpaca supports notional for Sell too usually, checking docs... 
            # Actually simplest is using notional for Buy and Qty for Sell or Notional for Sell.
            # Let's use notional for BUY and implicit qty calculation for SELL to be safe if full exit.
            side=side,
            time_in_force=TimeInForce.DAY
        )

        # Refined Sell Logic: 
        # If SELL, usually we want to close a qty. `notional` passed here is target value. 
        # If we want to support fractional sell by value, we can pass notional.
        if side == OrderSide.SELL:
            # FIX: Use close_position for SELL to avoid "insufficient qty" errors due to fractional rounding 
            # or price fluctuations when using 'notional'.
            # Assumes we want to close the ENTIRE position.
            try:
                self.client.close_position(symbol_or_asset_id=symbol)
                timestamp = datetime.now(timezone.utc).isoformat()
                return TradeResult(
                    action="SELL",
                    symbol=symbol,
                    qty=0, # Unknown until fill, simplified
                    price=price,
                    notional=notional,
                    timestamp=timestamp
                )
            except Exception as e:
                # Fallback if close_position fails (e.g. 404/no pos) or partial logic needed later
                raise RuntimeError(f"Alpaca Close Failed: {e}")

        try:
            order = self.client.submit_order(order_data=req)
            
            # For BUY orders, we handle SL/TP logic locally or separate orders?
            # Creating bracket orders via API is possible but complex for simple "update" logic.
            # Simplified approach: We execute the main order. SL/TP are stored in local state for monitoring.
            # The bot monitors price and issues SELL calls when SL/TP hit. (Managed in main.py auto_exit)
            
            # Timestamp
            timestamp = datetime.now(timezone.utc).isoformat()
            
            # Approximate execution price (real price not known until fill)
            # We use current price for logging
            
            result = TradeResult(
                action=action.upper(),
                symbol=symbol,
                qty=notional / price, # Approx
                price=price,
                notional=notional,
                timestamp=timestamp
            )
            
            # Update local state tentatively (will be fixed by next sync)
            if side == OrderSide.BUY:
                portfolio.cash -= notional
                # Store open_date for same-day sell guard
                today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                portfolio.positions[symbol] = {
                    "qty": notional / price,
                    "avg_entry": price,
                    "open_date": today_str,  # Track when opened for PDT
                    "sl": sl_price,
                    "tp": tp_price,
                }
            
            return result
            
        except Exception as e:
            raise RuntimeError(f"Alpaca Order Failed: {e}")

    def close_all_positions(self):
        self.client.close_all_positions(cancel_orders=True)
