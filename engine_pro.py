import pandas_ta as ta
import numpy as np

class InstitutionalEngine:
    def __init__(self, stock_df, market_df, midcap_df):
        self.df = stock_df
        self.mkt = market_df
        self.mid = midcap_df

    def calculate_indicators(self, df):
        df['ema20'] = ta.ema(df['Close'], length=20)
        df['ema50'] = ta.ema(df['Close'], length=50)
        df['ema200'] = ta.ema(df['Close'], length=200)
        df['rsi'] = ta.rsi(df['Close'], length=14)
        df['atr'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        df['vol_sma'] = ta.sma(df['Volume'], length=20)
        return df

    def get_contextual_score(self):
        self.df = self.calculate_indicators(self.df)
        self.mkt = self.calculate_indicators(self.mkt)
        
        last = self.df.iloc[-1]
        mkt_last = self.mkt.iloc[-1]
        
        scores = {}
        explanations = []

        # 4. MARKET REGIME (5 Points)
        mkt_regime_score = 0
        if mkt_last['Close'] > mkt_last['ema200']: mkt_regime_score += 3
        if mkt_last['rsi'] > 50: mkt_regime_score += 2
        scores['Market'] = mkt_regime_score
        explanations.append(f"Market Status: {mkt_regime_score}/5")

        # 5. SECTOR/RELATIVE STRENGTH (5 Points)
        # Simplified: Stock Return vs Market Return over 3 months
        stock_ret = (self.df['Close'].iloc[-1] / self.df['Close'].iloc[-63]) - 1
        mkt_ret = (self.mkt['Close'].iloc[-1] / self.mkt['Close'].iloc[-63]) - 1
        rs_score = 5 if stock_ret > mkt_ret else 2
        scores['Sector'] = rs_score
        explanations.append(f"Relative Strength: {rs_score}/5")

        # 3. BREAKOUT DETECTION (20 Points)
        brk_score = 0
        setup_type = "Base Formation"
        h20 = self.df['High'].iloc[-21:-1].max()
        h50 = self.df['High'].iloc[-51:-1].max()
        h252 = self.df['High'].iloc[-253:-1].max()
        
        if last['Close'] > h252: 
            brk_score = 20; setup_type = "52-Week Breakout"
        elif last['Close'] > h50: 
            brk_score = 15; setup_type = "50-Day Breakout"
        elif last['Close'] > h20: 
            brk_score = 10; setup_type = "20-Day Breakout"
        scores['Breakout'] = brk_score
        explanations.append(f"Breakout Factor: {brk_score}/20 ({setup_type})")

        # 6. VCP DETECTION (Advanced)
        # ATR contracting, Volume contracting, narrowing range
        atr_contract = last['atr'] < self.df['atr'].iloc[-10:-1].mean()
        vol_contract = last['Volume'] < self.df['vol_sma'].iloc[-1]
        if atr_contract and vol_contract:
            setup_type = "VCP Pattern"
            explanations.append("VCP Characteristics Detected")

        # 7. TREND (30) & MOMENTUM (20) & VOLUME (20)
        trend = 0
        if last['Close'] > last['ema200']: trend += 15
        if last['ema50'] > last['ema200']: trend += 15
        scores['Trend'] = trend
        
        mom = 0
        if 50 < last['rsi'] < 70: mom += 20
        scores['Momentum'] = mom
        
        vol = 0
        if last['Volume'] > last['vol_sma'] * 1.5: vol += 20
        elif last['Volume'] > last['vol_sma']: vol += 10
        scores['Volume'] = vol

        total_score = sum(scores.values())
        return total_score, setup_type, " | ".join(explanations)