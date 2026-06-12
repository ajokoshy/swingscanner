import yfinance as yf
import pandas as pd

class DataPipeline:
    @staticmethod
    def get_clean_data(symbol):
        try:
            # Download 2 years of data for EMA200 stability
            df = yf.download(f"{symbol}.NS", period="2y", interval="1d", progress=False, auto_adjust=True)
            
            if df.empty or len(df) < 200:
                return None

            # 1. Fix Multi-Index
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            # 2. FIX FOR 'nan': Drop rows where Close or Volume is missing
            # This removes the empty "today" candle yfinance often adds
            df = df.dropna(subset=['Close', 'Volume'])
            
            # 3. Liquidity Filter (Institutional Requirement)
            # Exclude stocks with Avg Daily Turnover < 5 Crores
            avg_turnover = (df['Close'] * df['Volume']).tail(20).mean()
            if avg_turnover < 50_000_000: 
                return None

            return df
        except Exception:
            return None
