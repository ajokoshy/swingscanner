import numpy as np

class RiskManager:
    @staticmethod
    def get_trade_setup(df):
        last = df.iloc[-1]
        price = float(last['Close'])
        atr = float(last['atr'])
        
        # 1. Professional ATR-Based Stop Loss (2.0x ATR)
        stop_loss = price - (2.0 * atr)
        risk_per_share = price - stop_loss
        
        if risk_per_share <= 0:
            return None

        # 2. Realistic 3-Tier Targets
        target1 = price + (risk_per_share * 2.0) # 2R
        target2 = price + (risk_per_share * 3.0) # 3R
        target3 = price + (risk_per_share * 5.0) # 5R

        return {
            "entry": round(price, 2),
            "stop_loss": round(stop_loss, 2),
            "target1": round(target1, 2),
            "target2": round(target2, 2),
            "target3": round(target3, 2),
            "rr": round((target1 - price) / risk_per_share, 2),
            "atr": round(atr, 2)
        }