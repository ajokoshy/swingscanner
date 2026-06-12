class RiskManager:
    @staticmethod
    def get_levels(df):
        # 1. FIX ATR BUG: Ensure indicators are fresh
        df['ema50'] = ta.ema(df['Close'], length=50)
        df['atr'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        
        last = df.iloc[-1]
        price = last['Close']
        atr = last['atr']
        
        # 11. REJECT TRADE SETUPS WHERE R/R < 2
        stop_loss = price - (2 * atr)
        risk = price - stop_loss
        if risk <= 0: return None
        
        target1 = price + (risk * 2) # 2R
        target2 = price + (risk * 3)
        target3 = price + (risk * 5)
        rr = (target1 - price) / risk
        
        if rr < 1.9: # 11. Reject
            return None
            
        return {
            "entry": round(price, 2), "stop_loss": round(stop_loss, 2),
            "t1": round(target1, 2), "t2": round(target2, 2), "t3": round(target3, 2),
            "rr": round(rr, 2)
        }