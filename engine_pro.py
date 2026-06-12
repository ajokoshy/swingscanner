import pandas_ta as ta
import numpy as np
import pandas as pd

class InstitutionalEngine:
    def __init__(self, stock_df, market_df, midcap_df):
        self.df = stock_df.copy()
        self.mkt = market_df.copy()
        self.mid = midcap_df.copy()

    def calculate_indicators(self, df):
        # Professional standard indicator suite
        df['ema20'] = ta.ema(df['Close'], length=20)
        df['ema50'] = ta.ema(df['Close'], length=50)
        df['ema200'] = ta.ema(df['Close'], length=200)
        df['rsi'] = ta.rsi(df['Close'], length=14)
        df['atr'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        df['vol_sma'] = ta.sma(df['Volume'], length=20)
        # 20, 50, and 252 day highs for breakout detection
        df['h20'] = df['High'].rolling(window=20).max().shift(1)
        df['h50'] = df['High'].rolling(window=50).max().shift(1)
        df['h252'] = df['High'].rolling(window=252).max().shift(1)
        return df.dropna(subset=['ema200', 'rsi', 'atr'])

    def get_contextual_score(self):
        """Final Institutional Scoring Engine (Total 100 Points)"""
        self.df = self.calculate_indicators(self.df)
        self.mkt = self.calculate_indicators(self.mkt)
        
        if self.df.empty or self.mkt.empty:
            return 0, "No Setup", "Insufficient historical data"

        last = self.df.iloc[-1]
        mkt_last = self.mkt.iloc[-1]
        
        score_components = {
            "Trend": 0,      # Max 30
            "Momentum": 0,   # Max 20
            "Volume": 0,     # Max 20
            "Breakout": 0,   # Max 20
            "Market": 0,     # Max 5
            "Sector": 0      # Max 5
        }
        explanations = []

        # 1. TREND (30 Points)
        if last['Close'] > last['ema200']: score_components["Trend"] += 15
        if last['ema20'] > last['ema50'] > last['ema200']: score_components["Trend"] += 15
        explanations.append(f"Trend: {score_components['Trend']}/30")

        # 2. MOMENTUM (20 Points)
        if 55 <= last['rsi'] <= 70: 
            score_components["Momentum"] = 20
        elif 45 <= last['rsi'] < 55:
            score_components["Momentum"] = 10
        explanations.append(f"Momentum: {score_components['Momentum']}/20")

        # 3. VOLUME (20 Points)
        if last['Volume'] > (last['vol_sma'] * 1.5):
            score_components["Volume"] = 20
            explanations.append("High Volume Accumulation Detected")
        elif last['Volume'] > last['vol_sma']:
            score_components["Volume"] = 10
        explanations.append(f"Volume: {score_components['Volume']}/20")

        # 4. BREAKOUT & SETUP DETECTION (20 Points)
        setup_type = "Base Formation"
        if last['Close'] > last['h252']:
            score_components["Breakout"] = 20
            setup_type = "52-Week High Breakout"
        elif last['Close'] > last['h50']:
            score_components["Breakout"] = 15
            setup_type = "50-Day High Breakout"
        elif last['Close'] > last['h20']:
            score_components["Breakout"] = 10
            setup_type = "20-Day High Breakout"

        # VCP Detection Logic (ATR & Vol Contraction)
        atr_now = last['atr']
        atr_avg = self.df['atr'].iloc[-10:-1].mean()
        vol_now = last['Volume']
        vol_avg = last['vol_sma']
        
        if atr_now < (atr_avg * 0.9) and vol_now < vol_avg:
            setup_type = "Volatility Contraction (VCP)"
            score_components["Breakout"] = max(score_components["Breakout"], 18)
            explanations.append("Narrowing Range & Volume (VCP)")

        # Pullback Logic
        if 0.98 <= (last['Close'] / last['ema50']) <= 1.02:
            setup_type = "Pullback to EMA50"
            score_components["Breakout"] = max(score_components["Breakout"], 15)

        explanations.append(f"Setup: {score_components['Breakout']}/20 ({setup_type})")

        # 5. MARKET REGIME (5 Points)
        if mkt_last['Close'] > mkt_last['ema200']: score_components["Market"] += 3
        if mkt_last['rsi'] > 50: score_components["Market"] += 2
        explanations.append(f"Market Filter: {score_components['Market']}/5")

        # 6. SECTOR/RELATIVE STRENGTH (5 Points)
        # Relative Strength: Stock 3-Month Performance vs Index
        stock_3m = (self.df['Close'].iloc[-1] / self.df['Close'].iloc[-63]) - 1
        mkt_3m = (self.mkt['Close'].iloc[-1] / self.mkt['Close'].iloc[-63]) - 1
        if stock_3m > mkt_3m:
            score_components["Sector"] = 5
            explanations.append("Outperforming Nifty 50 (RS Strong)")
        else:
            score_components["Sector"] = 2
            explanations.append("Underperforming Market")

        total_score = sum(score_components.values())
        return int(total_score), setup_type, " | ".join(explanations)
