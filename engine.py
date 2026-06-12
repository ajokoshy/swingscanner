import pandas as pd
import pandas_ta as ta
import yfinance as yf

class SwingEngine:
    def __init__(self, symbol):
        self.symbol = f"{symbol.upper()}.NS" if not symbol.endswith(".NS") else symbol.upper()
        self.df = None

    def fetch_data(self):
        try:
            # 1. Download data
            # auto_adjust=True and actions=False keeps the dataframe simple
            data = yf.download(self.symbol, period="2y", interval="1d", progress=False, auto_adjust=True)
            
            if data.empty:
                return False

            # 2. FIX MULTI-INDEX (Crucial step)
            # This flattens columns like ('Close', 'RELIANCE.NS') to just 'Close'
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            
            # 3. Clean any duplicate column names and set index
            self.df = data.copy()
            return True
        except Exception as e:
            print(f"Error fetching data: {e}")
            return False

    def analyze(self):
        # We need at least 200 days for EMA200
        if self.df is None or len(self.df) < 200:
            return None
        
        df = self.df.copy()
        
        # 1. Calculate Technical Indicators using pandas_ta
        df['ema20'] = ta.ema(df['Close'], length=20)
        df['ema50'] = ta.ema(df['Close'], length=50)
        df['ema200'] = ta.ema(df['Close'], length=200)
        df['rsi'] = ta.rsi(df['Close'], length=14)
        df['vol_sma'] = ta.sma(df['Volume'], length=20)
        
        # MACD returns a DataFrame, so we join it
        macd = ta.macd(df['Close'])
        df = pd.concat([df, macd], axis=1)

        # 2. Extract ONLY the last row and convert to a flat Dictionary
        # This converts Pandas Series into simple Python floats/strings
        # It completely bypasses the "Identically-labeled Series" error
        last = df.iloc[-1].to_dict()
        
        score = 0
        reasons = []
        
        # Helper to get numeric values safely from the dictionary
        def get_val(key):
            val = last.get(key, 0)
            try:
                # Handle cases where value might be a series or nan
                return float(val.iloc[0]) if hasattr(val, 'iloc') else float(val)
            except:
                return 0.0

        close_p = get_val('Close')
        ema20 = get_val('ema20')
        ema50 = get_val('ema50')
        ema200 = get_val('ema200')
        rsi = get_val('rsi')
        vol = get_val('Volume')
        vol_sma = get_val('vol_sma')

        # 3. Scoring Logic
        # Trend
        if close_p > ema200: 
            score += 20
            reasons.append("Price above EMA200")
        if ema20 > ema50: 
            score += 15
            reasons.append("Short-term EMA Bullish Alignment")
        
        # Momentum
        if 45 < rsi < 70: 
            score += 20
            reasons.append("RSI in Bullish Zone")
            
        # MACD check (Finding the histogram column dynamically)
        hist_col = [c for c in df.columns if 'MACDh' in str(c)]
        if hist_col and get_val(hist_col[0]) > 0:
            score += 15
            reasons.append("MACD Histogram Positive")
        
        # Volume
        if vol > vol_sma * 1.5: 
            score += 30
            reasons.append("High Volume Breakout")
        elif vol > vol_sma: 
            score += 10
            reasons.append("Volume above average")

        # 4. Trade Setup Calculation
        stop_loss = min(ema50, close_p * 0.95)
        risk = close_p - stop_loss
        
        # Guard against zero risk to prevent division error
        if risk <= 0: risk = close_p * 0.02 

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
