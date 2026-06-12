import pandas as pd
import pandas_ta as ta
import yfinance as yf

class SwingEngine:
    def __init__(self, symbol):
        self.symbol = f"{symbol.upper()}.NS" if not symbol.endswith(".NS") else symbol.upper()
        self.df = None

    def fetch_data(self):
        self.df = yf.download(self.symbol, period="2y", interval="1d", progress=False)
        return not self.df.empty

    def analyze(self):
        if self.df is None or len(self.df) < 200:
            return None
        
        df = self.df.copy()
        # 1. Indicators
        df['ema20'] = ta.ema(df['Close'], length=20)
        df['ema50'] = ta.ema(df['Close'], length=50)
        df['ema200'] = ta.ema(df['Close'], length=200)
        df['rsi'] = ta.rsi(df['Close'], length=14)
        df['vol_sma'] = ta.sma(df['Volume'], length=20)
        macd = ta.macd(df['Close'])
        df = pd.concat([df, macd], axis=1)

        last = df.iloc[-1]
        prev = df.iloc[-2]

        # 2. Scoring Logic
        score = 0
        reasons = []
        
        # Trend
        if last['Close'] > last['ema200']: score += 20; reasons.append("Price > EMA200")
        if last['ema20'] > last['ema50']: score += 15; reasons.append("Bullish EMA Alignment")
        
        # Momentum
        if 45 < last['rsi'] < 70: score += 20; reasons.append("RSI Healthy")
        if last['MACDh_12_26_9'] > 0: score += 15; reasons.append("MACD Bullish")
        
        # Volume
        if last['Volume'] > last['vol_sma'] * 1.5: score += 30; reasons.append("Volume Breakout")
        elif last['Volume'] > last['vol_sma']: score += 10; reasons.append("Strong Volume")

        # 3. Setup Calculation
        curr_price = float(last['Close'])
        # Stop loss at EMA50 or 5% below price
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
            "reasons": ", ".join(reasons),
            "trend": "Bullish" if last['Close'] > last['ema200'] else "Bearish"
        }