import pandas_ta as ta
import numpy as np
import pandas as pd

class InstitutionalEngine:
    def __init__(self, stock_df, market_df, midcap_df):
        # We work with copies to avoid modifying original data
        self.df = stock_df.copy()
        self.mkt = market_df.copy()
        self.mid = midcap_df.copy()

    def calculate_indicators(self, df):
        # Indicator suite
        df['ema20'] = ta.ema(df['Close'], length=20)
        df['ema50'] = ta.ema(df['Close'], length=50)
        df['ema200'] = ta.ema(df['Close'], length=200)
        df['rsi'] = ta.rsi(df['Close'], length=14)
        df['atr'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        df['vol_sma'] = ta.sma(df['Volume'], length=20)

        # Breakout Reference Levels (Shifted by 1 to avoid look-ahead bias)
        df['h20'] = df['High'].rolling(window=20).max().shift(1)
        df['h50'] = df['High'].rolling(window=50).max().shift(1)
        df['h252'] = df['High'].rolling(window=252).max().shift(1)

        # Drop rows where critical indicators (EMA200) haven't formed yet
        return df.dropna(subset=['ema200', 'rsi', 'atr'])

    def get_contextual_score(self):
        """Institutional Scoring Engine (100 Points) with VCP Tightness Logic"""
        self.df = self.calculate_indicators(self.df)
        self.mkt = self.calculate_indicators(self.mkt)

        # 1. SAFETY CHECK: Ensure we have at least some valid data after indicators
        if len(self.df) < 5 or len(self.mkt) < 5:
            return 0, "Insufficient Data", "Stock history too short for institutional analysis"

        last = self.df.iloc[-1]
        mkt_last = self.mkt.iloc[-1]

        score_components = {"Trend": 0, "Momentum": 0, "Volume": 0, "Breakout": 0, "Market": 0, "Sector": 0}
        explanations = []

        # 2. TREND (30 Points)
        if last['Close'] > last['ema200']: score_components["Trend"] += 15
        if last['ema20'] > last['ema50'] > last['ema200']: score_components["Trend"] += 15
        explanations.append(f"Trend: {score_components['Trend']}/30")

        # 3. MOMENTUM (20 Points)
        rsi_val = last['rsi']
        if 55 <= rsi_val <= 70: score_components["Momentum"] = 20
        elif 45 <= rsi_val < 55: score_components["Momentum"] = 10
        explanations.append(f"Momentum: {score_components['Momentum']}/20")

        # 4. VOLUME (20 Points)
        if last['Volume'] > (last['vol_sma'] * 1.5):
            score_components["Volume"] = 20
            explanations.append("Institutional Vol Spike")
        elif last['Volume'] > last['vol_sma']:
            score_components["Volume"] = 10
        explanations.append(f"Volume: {score_components['Volume']}/20")

        # 5. BREAKOUT & SETUP DETECTION (20 Points)
        setup_type = "Base Formation"
        
        # Priority 1: Multi-day High Breakouts
        if len(self.df) >= 252 and last['Close'] > last['h252']:
            score_components["Breakout"] = 20
            setup_type = "52-Week High Breakout"
        elif last['Close'] > last['h50']:
            score_components["Breakout"] = 15
            setup_type = "50-Day High Breakout"
        elif last['Close'] > last['h20']:
            score_components["Breakout"] = 10
            setup_type = "20-Day High Breakout"

        # Priority 2: VCP Logic (ATR, Volume & Price Tightness)
        # Only applies if a major breakout wasn't already triggered.
        lookback = min(10, len(self.df))
        atr_avg = self.df['atr'].iloc[-lookback:-1].mean()
        # Calculate the high-to-low range over the last 10 days
        price_spread = (self.df['High'].iloc[-lookback:].max() / self.df['Low'].iloc[-lookback:].min()) - 1
        
        if score_components["Breakout"] == 0:
            if last['atr'] < (atr_avg * 0.9) and last['Volume'] < last['vol_sma'] and price_spread < 0.08:
                setup_type = "VCP Pattern"
                score_components["Breakout"] = 18
                explanations.append("VCP Tightness Detected (Vol/Price Contraction)")
            elif 0.98 <= (last['Close'] / last['ema50']) <= 1.02:
                setup_type = "Pullback to EMA50"
                score_components["Breakout"] = 15
                explanations.append("Healthy Pullback to EMA50")

        explanations.append(f"Setup: {score_components['Breakout']}/20 ({setup_type})")

        # 6. MARKET REGIME (5 Points)
        if mkt_last['Close'] > mkt_last['ema200']: score_components["Market"] += 3
        if mkt_last['rsi'] > 50: score_components["Market"] += 2
        explanations.append(f"Market: {score_components['Market']}/5")

        # 7. SECTOR / RELATIVE STRENGTH (5 Points)
        lookback_rs = min(63, len(self.df), len(self.mkt))
        if lookback_rs > 5:
            stock_ret = (self.df['Close'].iloc[-1] / self.df['Close'].iloc[-lookback_rs]) - 1
            mkt_ret = (self.mkt['Close'].iloc[-1] / self.mkt['Close'].iloc[-lookback_rs]) - 1
            if stock_ret > mkt_ret:
                score_components["Sector"] = 5
                explanations.append("RS Positive (Outperforming Nifty)")
            else:
                score_components["Sector"] = 2

        total_score = sum(score_components.values())
        return int(total_score), setup_type, " | ".join(explanations)
