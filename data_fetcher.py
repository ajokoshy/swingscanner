import re
import yfinance as yf
import pandas as pd
import io, requests
import time
import random
from curl_cffi import requests as crequests

class DataPipeline:
    # A list of real-world user agents to rotate
    _user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ]

    @staticmethod
    def get_nse500_symbols():
        url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
        try:
            # Using curl_cffi to impersonate browser for NSE website too
            response = crequests.get(url, impersonate="chrome110", timeout=15)
            df = pd.read_csv(io.StringIO(response.text))
            symbols = df['Symbol'].str.strip().unique().tolist()
            clean_symbols = [
                s for s in symbols 
                if re.match(r'^[A-Z0-9&-]+$', s) and not s.startswith("DUMMY")
            ]
            return clean_symbols
        except Exception as e:
            print(f"Error fetching NSE500 list: {e}")
            return ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY"]

    @staticmethod
    def fetch_market_data(symbol, period="2y"):
        """Resilient fetch for index data with TLS Impersonation."""
        sym = symbol if symbol.startswith("^") else f"{symbol}.NS"
        for attempt in range(3):
            try:
                # We use yf.download but with a randomized user agent
                df = yf.download(
                    sym, 
                    period=period, 
                    interval="1d", 
                    progress=False, 
                    auto_adjust=False,
                    headers={'User-Agent': random.choice(DataPipeline._user_agents)}
                )
                if df is not None and not df.empty:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    return df.dropna(subset=['Close'])
                time.sleep(random.uniform(2, 4))
            except Exception:
                time.sleep(2)
        return None

    @staticmethod
    def fetch_batch_data(symbols):
        """Downloads symbols in very small chunks with 'Fingerprint Spoofing'."""
        ns_symbols = [f"{s}.NS" for s in symbols]
        
        # Reduced chunk size to 15 for maximum safety against cloud blocking
        chunk_size = 15 
        chunks = [ns_symbols[i:i + chunk_size] for i in range(0, len(ns_symbols), chunk_size)]
        
        all_dfs = []
        
        for i, chunk in enumerate(chunks):
            try:
                # Institutional Jitter: Random sleep to avoid looking like a cron job
                if i > 0:
                    time.sleep(random.uniform(1.5, 3.5))
                
                print(f"Fetching chunk {i+1}/{len(chunks)}...")
                data = yf.download(
                    chunk,
                    period="2y",
                    interval="1d",
                    group_by='ticker',
                    auto_adjust=True,
                    progress=False,
                    threads=True,
                    headers={'User-Agent': random.choice(DataPipeline._user_agents)},
                    timeout=25
                )
                if not data.empty:
                    all_dfs.append(data)
            except Exception as e:
                print(f"Error in chunk {i}: {e}")
                continue
        
        if not all_dfs:
            return None
            
        return pd.concat(all_dfs, axis=1)
