import re
import yfinance as yf
from yahooquery import Ticker
import pandas as pd
import io, requests
import time
import random
from curl_cffi import requests as crequests

class DataPipeline:
    _user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0'
    ]

    @staticmethod
    def get_nse500_symbols():
        url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
        try:
            resp = crequests.get(url, impersonate="chrome110", timeout=15)
            df = pd.read_csv(io.StringIO(resp.text))
            symbols = df['Symbol'].str.strip().unique().tolist()
            return [s for s in symbols if re.match(r'^[A-Z0-9&-]+$', s) and not s.startswith("DUMMY")]
        except:
            return ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "M&M", "L&T"]

    @staticmethod
    def fetch_market_data(symbol):
        """Uses yahooquery for Indices - much more stable than yfinance."""
        try:
            # ^NSEI, ^NSEMDCP50
            t = Ticker(symbol, asynchronous=True)
            df = t.history(period="2y", interval="1d")
            if df.empty: return None
            
            # yahooquery returns a multi-index (symbol, date), we flatten it
            if isinstance(df.index, pd.MultiIndex):
                df = df.reset_index().set_index('date')
            
            # Standardize column names to match our engine
            df = df.rename(columns={'adjclose': 'Close', 'high': 'High', 'low': 'Low', 'volume': 'Volume', 'open': 'Open'})
            return df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
        except:
            return None

    @staticmethod
    def fetch_batch_data(symbols):
        """Downloads symbols in ultra-small chunks with randomized headers."""
        ns_symbols = [f"{s}.NS" for s in symbols]
        # Smaller chunks (10) are less likely to trigger firewalls
        chunk_size = 10 
        chunks = [ns_symbols[i:i + chunk_size] for i in range(0, len(ns_symbols), chunk_size)]
        
        all_dfs = []
        session = requests.Session()
        
        for i, chunk in enumerate(chunks):
            try:
                # Institutional Jitter: Longer random wait
                time.sleep(random.uniform(2.5, 5.0))
                
                # Update session headers for every chunk to look like a new user
                session.headers.update({'User-Agent': random.choice(DataPipeline._user_agents)})
                
                data = yf.download(
                    chunk,
                    period="2y",
                    interval="1d",
                    group_by='ticker',
                    auto_adjust=True,
                    progress=False,
                    threads=True,
                    session=session,
                    timeout=20
                )
                if not data.empty:
                    all_dfs.append(data)
                
                # If we've hit 100 stocks, take a longer 'Human Break'
                if (i + 1) % 10 == 0:
                    time.sleep(10)
                    
            except Exception as e:
                print(f"Skipping chunk {i}: Yahoo rejected connection.")
                continue
        
        return pd.concat(all_dfs, axis=1) if all_dfs else None
