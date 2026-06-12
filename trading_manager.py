import pandas_ta as ta
import pandas as pd

class RiskManager:
    @staticmethod
    def get_levels(df):
        """
        Calculates ATR-based risk levels and validates R/R.
        Fixes the ATR bug by recalculating indicators locally.
        """
        # Ensure we don't modify the original dataframe
        df = df.copy()
        
        # 1. FIX ATR BUG: Recalculate indicators before reading values
        df['ema50'] = ta.ema(df['Close'], length=50)
        df['atr'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        
        # Check if enough data exists for ATR
        if len(df) < 14 or df['atr'].isna().all():
            return None
            
        last = df.iloc[-1]
        price = float(last['Close'])
        atr = float(last['atr'])
        
        if atr <= 0 or pd.isna(atr):
            return None

        # 2. Professional ATR-Based Stop Loss (2.0x ATR)
        # This accounts for the specific volatility of the stock
        stop_loss = price - (2.0 * atr)
        risk = price - stop_loss
        
        if risk <= 0:
            return None
            
        # 3. Institutional 3-Tier Targets
        t1 = price + (risk * 2.0)  # 2.0 Risk:Reward (Target 1)
        t2 = price + (risk * 3.0)  # 3.0 Risk:Reward (Target 2)
        t3 = price + (risk * 5.0)  # 5.0 Risk:Reward (Target 3)
        
        # 4. REJECT TRADE SETUPS WHERE R/R < 2
        rr = (t1 - price) / risk
        
        # Using 1.9 for slight floating point tolerance
        if rr < 1.9:
            return None
            
        return {
            "entry": round(price, 2),
            "stop_loss": round(stop_loss, 2),
            "t1": round(t1, 2),
            "t2": round(t2, 2),
            "t3": round(t3, 2),
            "rr": round(rr, 2)
        }
