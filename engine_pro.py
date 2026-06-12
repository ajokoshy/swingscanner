import pandas_ta as ta
import numpy as np

class TradingEngine:
    def __init__(self, df):
        self.df = df

    def calculate_indicators(self):
        df = self.df
        df['ema50'] = ta.ema(df['Close'], length=50)
        df['ema200'] = ta.ema(df['Close'], length=200)
        df['rsi'] = ta.rsi(df['Close'], length=14)
        df['atr'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        df['vol_sma'] = ta.sma(df['Volume'], length=20)
        return df

    def get_score(self):
        df = self.calculate_indicators()
        last = df.iloc[-1]
        score = 0
        reasons = []

        # 1. Trend (30%)
        if last['Close'] > last['ema200']: score += 20; reasons.append("Primary Trend Bullish")
        if last['ema50'] > last['ema200']: score += 10; reasons.append("Golden Alignment")

        # 2. VCP / Volatility Contraction (20%)
        recent_vol = df['atr'].tail(5).mean()
        prev_vol = df['atr'].shift(10).tail(5).mean()
        if recent_vol < prev_vol * 0.8: score += 20; reasons.append("Volatility Contraction (VCP)")

        # 3. Volume / Accumulation (20%)
        if last['Volume'] > last['vol_sma'] * 1.5: score += 20; reasons.append("Institutional Accumulation")

        # 4. Momentum (20%)
        if 50 < last['rsi'] < 70: score += 20; reasons.append("Momentum in Power Zone")

        return score, reasons

    def get_risk_levels(self):
        last = self.df.iloc[-1]
        close = last['Close']
        atr = last['atr']

        # Professional Stop: 2 * ATR
        stop_loss = close - (2 * atr)
        risk = close - stop_loss
        
        return {
            "entry": round(close, 2),
            "stop_loss": round(stop_loss, 2),
            "target1": round(close + (risk * 2), 2),  # 2R
            "target2": round(close + (risk * 4), 2),  # 4R
            "rr": "1:2 Min"
        }