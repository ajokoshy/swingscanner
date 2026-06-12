import pandas as pd
import pandas_ta as ta
import yfinance as yf
import numpy as np

class SwingEngine:
    def __init__(self, symbol):
        self.symbol = f"{symbol.upper()}.NS" if not symbol.endswith(".NS") else symbol.upper()
        self.df = None

    def fetch_data(self):
        try:
            # 1. Download data
            data = yf.download(self.symbol, period="2y", interval="1d", progress=False, auto_adjust=True)
            
            if data.empty:
                return False

            # 2. Flatten MultiIndex columns
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            
            # 3. IMPORTANT: Remove any rows that have no price data (Fixes the 'nan' issue)
            data = data.dropna(subset=['Close'])
            
            self.df = data.copy()
            return True
        except Exception as e:
            print(f"Error fetching data: {e}")
            return False

    def analyze(self):
        # We need data to calculate indicators
        if self.df is None or len(self.df) < 20:
            return None
        
        df = self.df.copy()
        
        # 1. Calculate Technical Indicators
        df['ema20'] = ta.ema(df['Close'], length=20)
        df['ema50'] = ta.ema(df['Close'], length=50)
        df['ema200'] = ta.ema(df['Close'], length=200)
        df['rsi'] = ta.rsi(df['Close'], length=14)
        df['vol_sma'] = ta.sma(df['Volume'], length=20)
        
        macd = ta.macd(df['Close'])
        df = pd.concat([df, macd], axis=1)

        # 2. Drop rows where indicators are NaN (the first 200 rows)
        # Then pick the very last valid row
        df = df.dropna(subset=['ema20', 'rsi'])
        if df.empty:
            return None
            
        last = df.iloc[-1].to_dict()
        
        # Helper to get numeric values safely
        def get_val(key):
            val = last.get(key, 0)
            if pd.isna(val): return 0.0
            return float(val)

        close_p = get_val('Close')
        ema20 = get_val('ema20')
        ema50 = get_val('ema50')
        ema200 = get_val('ema200')
        rsi = get_val('rsi')
        vol = get_val('Volume')
        vol_sma = get_val('vol_sma')

        # 3. Scoring Logic
        score = 0
        reasons = []
        
        if close_p > ema200 and ema200 > 0: 
            score += 20
            reasons.append("Price above EMA200")
        if ema20 > ema50: 
            score += 15
            reasons.append("Short-term EMA Bullish Alignment")
        if 45 < rsi < 70: 
            score += 20
            reasons.append("RSI in Bullish Zone")
            
        hist_col = [c for c in df.columns if 'MACDh' in str(c)]
        if hist_col and get_val(hist_col[0]) > 0:
            score += 15
            reasons.append("MACD Histogram Positive")
        
        if vol > vol_sma * 1.5: 
            score += 30
            reasons.append("High Volume Breakout")
        elif vol > vol_sma: 
            score += 10
            reasons.append("Volume above average")

        # 4. Trade Setup Calculation (using 1:2.5 Risk Reward)
        # Use EMA50 as stop loss, but ensure it's below current price
        stop_loss = ema50 if ema50 < close_p else close_p * 0.95
        risk = close_p - stop_loss
        
        # Prevent math errors if risk is somehow zero
        if risk <= 0:
            risk = close_p * 0.02
            stop_loss = close_p - risk

        return {
            "symbol": self.symbol.replace(".NS", ""),
            "score": score,
            "classification": "Strong Swing Candidate" if score >= 80 else "Watchlist" if score >= 60 else "Avoid",
            "entry": round(close_p, 2),
            "stop_loss": round(stop_loss, 2),
            "target_1": round(close_p + (risk * 1.5), 2),
            "target_2": round(close_p + (risk * 2.5), 2),
            "risk_reward": "1:2.5",
            "reasons": ", ".join(reasons)
        }
