import pandas as pd
import pandas_ta as ta
import yfinance as yf

class SwingEngine:
    def __init__(self, symbol):
        self.symbol = f"{symbol.upper()}.NS" if not symbol.endswith(".NS") else symbol.upper()
        self.df = None

    def fetch_data(self):
        # Download data
        data = yf.download(self.symbol, period="2y", interval="1d", progress=False)
        
        if data.empty:
            return False

        # --- FIX FOR MULTI-INDEX ERROR ---
        # If columns have two levels (e.g., ['Close', 'RELIANCE.NS']), flatten to one level
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        
        # Ensure we don't have duplicate column names and data is 1D
        self.df = data.copy()
        return True

    def analyze(self):
        if self.df is None or len(self.df) < 200:
            return None
        
        df = self.df.copy()
        
        # 1. Technical Indicators
        df['ema20'] = ta.ema(df['Close'], length=20)
        df['ema50'] = ta.ema(df['Close'], length=50)
        df['ema200'] = ta.ema(df['Close'], length=200)
        df['rsi'] = ta.rsi(df['Close'], length=14)
        df['vol_sma'] = ta.sma(df['Volume'], length=20)
        
        macd = ta.macd(df['Close'])
        df = pd.concat([df, macd], axis=1)

        # Get the very last row as a simple dictionary to avoid Series comparison errors
        last = df.iloc[-1].to_dict()
        
        # 2. Scoring Logic
        score = 0
        reasons = []
        
        # Trend (Using float() to ensure single value comparison)
        if float(last['Close']) > float(last['ema200']): 
            score += 20
            reasons.append("Price > EMA200")
            
        if float(last['ema20']) > float(last['ema50']): 
            score += 15
            reasons.append("Bullish EMA Alignment")
        
        # Momentum
        if 45 < float(last['rsi']) < 70: 
            score += 20
            reasons.append("RSI Healthy")
            
        # MACD Histogram key name usually looks like MACDh_12_26_9
        hist_col = [c for c in df.columns if 'MACDh' in c]
        if hist_col and float(last[hist_col[0]]) > 0:
            score += 15
            reasons.append("MACD Bullish")
        
        # Volume
        if float(last['Volume']) > float(last['vol_sma']) * 1.5: 
            score += 30
            reasons.append("Volume Breakout")
        elif float(last['Volume']) > float(last['vol_sma']): 
            score += 10
            reasons.append("Strong Volume")

        # 3. Setup Calculation
        curr_price = float(last['Close'])
        stop_loss = min(float(last['ema50']), curr_price * 0.95)
        risk = curr_price - stop_loss
        
        return {
            "symbol": self.symbol.replace(".NS", ""),
            "score": score,
            "classification": "Strong Swing Candidate" if score >= 80 else "Watchlist" if score >= 60 else "Avoid",
            "entry": round(curr_price, 2),
            "stop_loss": round(stop_loss, 2),
            "target_1": round(curr_price + (risk * 1.5), 2),
            "target_2": round(curr_price + (risk * 2.5), 2),
            "risk_reward": "1:2.5",
            "reasons": ", ".join(reasons)
        }
