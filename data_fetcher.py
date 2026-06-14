import re
import yfinance as yf
import pandas as pd
import io, requests
import time

class DataPipeline:
    # Set up a session with a real browser Header to avoid being blocked
    _session = requests.Session()
    _session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })

    @staticmethod
    def get_nse500_symbols():
        url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
        try:
            response = DataPipeline._session.get(url, timeout=15)
            df = pd.read_csv(io.StringIO(response.text))
            symbols = df['Symbol'].str.strip().unique().tolist()
            clean_symbols = [
                s for s in symbols 
                if re.match(r'^[A-Z0-9&-]+$', s) and not s.startswith("DUMMY")
            ]
            return clean_symbols
        except Exception as e:
            print(f"Error fetching NSE500 list: {e}")
            return ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "M&M", "L&T"]

    @staticmethod
    def fetch_market_data(symbol, period="2y"):
        """Resilient fetch for index data with Browser headers."""
        sym = symbol if symbol.startswith("^") else f"{symbol}.NS"
        for attempt in range(3):
            try:
                # auto_adjust=False is mandatory for Indices on new Yahoo API
                df = yf.download(sym, period=period, interval="1d", progress=False, 
                                 auto_adjust=False, session=DataPipeline._session)
                if df is not None and not df.empty:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    return df.dropna(subset=['Close'])
                time.sleep(2)
            except Exception:
                time.sleep(2)
        return None

    @staticmethod
    def fetch_batch_data(symbols):
        """Downloads symbols in chunks of 50 to avoid Yahoo rate-limits."""
        ns_symbols = [f"{s}.NS" for s in symbols]
        chunk_size = 50
        chunks = [ns_symbols[i:i + chunk_size] for i in range(0, len(ns_symbols), chunk_size)]
        
        all_dfs = []
        
        for i, chunk in enumerate(chunks):
            try:
                print(f"Downloading chunk {i+1}/{len(chunks)}...")
                # Fetching 50 stocks at a time is the 'Institutional Sweet Spot'
                data = yf.download(
                    chunk,
                    period="2y",
                    interval="1d",
                    group_by='ticker',
                    auto_adjust=True,
                    progress=False,
                    threads=True,
                    session=DataPipeline._session,
                    timeout=20
                )
                if not data.empty:
                    all_dfs.append(data)
                
                # Tiny sleep between chunks to avoid 'Burst' detection
                time.sleep(1)
            except Exception as e:
                print(f"Error in chunk {i}: {e}")
                continue
        
        if not all_dfs:
            return None
            
        return pd.concat(all_dfs, axis=1)
