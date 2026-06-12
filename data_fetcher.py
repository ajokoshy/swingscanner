import yfinance as yf
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

class DataPipeline:
    @staticmethod
    def fetch_single(symbol):
        try:
            # auto_adjust=True is critical for price integrity
            df = yf.download(f"{symbol}.NS", period="2y", interval="1d", progress=False, auto_adjust=True)
            if df.empty or len(df) < 200: return None
            
            # Flatten MultiIndex
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # Liquidity Filter: Avg Daily Turnover > 1 Crore (approx)
            avg_volume = df['Volume'].tail(20).mean()
            avg_price = df['Close'].tail(20).mean()
            if (avg_volume * avg_price) < 10000000: return None 
            
            return df.dropna()
        except:
            return None

    @staticmethod
    def fetch_batch(symbols):
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(DataPipeline.fetch_single, symbols))
        return {s: r for s, r in zip(symbols, results) if r is not None}