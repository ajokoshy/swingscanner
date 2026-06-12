import pandas_ta as ta

class ScoringEngine:
    @staticmethod
    def apply_indicators(df):
        df['ema50'] = ta.ema(df['Close'], length=50)
        df['ema200'] = ta.ema(df['Close'], length=200)
        df['rsi'] = ta.rsi(df['Close'], length=14)
        df['atr'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        df['vol_sma'] = ta.sma(df['Volume'], length=20)
        return df.dropna(subset=['ema200', 'atr'])

    @staticmethod
    def calculate_score(df):
        last = df.iloc[-1]
        score = 0
        factors = []

        # Trend (30%)
        if last['Close'] > last['ema200']:
            score += 30
            factors.append("Above EMA200 (Long Term Bullish)")
        
        # Momentum (20%)
        if 50 < last['rsi'] < 70:
            score += 20
            factors.append("RSI in Momentum Zone")
        
        # Volume/Accumulation (20%)
        if last['Volume'] > last['vol_sma'] * 1.5:
            score += 20
            factors.append("Institutional Volume Spike")

        # Mean Reversion / Pullback (30%)
        # Check if price is within 2% of EMA50 (Healthy pullback)
        if 0.98 <= (last['Close'] / last['ema50']) <= 1.02:
            score += 30
            factors.append("Price at EMA50 Support")

        return score, factors
