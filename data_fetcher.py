import re
import yfinance as yf
import pandas as pd
import io, requests
import time
import random
from curl_cffi import requests as crequests

class DataPipeline:
    # Use a persistent session to keep cookies/crumbs alive
    _session = requests.Session()
    
    _user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0'
    ]

    @staticmethod
    def _prime_session():
        """Prime the session by visiting Yahoo's home page to get a cookie/crumb."""
        try:
            headers = {'User-Agent': random.choice(DataPipeline._user_agents)}
            DataPipeline._session.get("https://fc.yahoo.com", headers=headers, timeout=10)
            DataPipeline._session.get("https://finance.yahoo.com", headers=headers, timeout=10)
        except:
            pass

    @staticmethod
    def get_nse500_symbols():
        url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
        headers = {'User-Agent': random.choice(DataPipeline._user_agents)}
        try:
            # NSE website is less strict but still needs a user-agent
            response = requests.get(url, headers=headers, timeout=15)
            df = pd.read_csv(io.StringIO(response.text))
            symbols = df['Symbol'].str.strip().unique().tolist()
            return [s for s in symbols if re.match(r'^[A-Z0-9&-]+$', s) and not s.startswith("DUMMY")]
        except Exception as e:
            print(f"Error fetching symbols: {e}")
            return ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY"]

    @staticmethod
    def fetch_market_data(symbol, period="2y"):
        """Resilient fetch for index data using the primed session."""
        DataPipeline._prime_session()
        sym = symbol if symbol.startswith("^") else f"{symbol}.NS"
        
        headers = {'User-Agent': random.choice(DataPipeline._user_agents)}
        try:
            # We use yf.Ticker object for more robust fetching of single items
            ticker = yf.Ticker(sym, session=DataPipeline._session)
            df = ticker.history(period=period, interval="1d", auto_adjust=True)
            
            if df.empty: return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df.dropna(subset=['Close'])
        except:
            return None

    @staticmethod
    def fetch_batch_data(symbols):
        """Institutional Stealth Batch: Small chunks, randomized headers, and session priming."""
        DataPipeline._prime_session()
        ns_symbols = [f"{s}.NS" for s in symbols]
        
        # Chunks of 5 are extremely safe for Cloud IP ranges
        chunk_size = 5 
        chunks = [ns_symbols[i:i + chunk_size] for i in range(0, len(ns_symbols), chunk_size)]
        
        all_dfs = []
        total_chunks = len(chunks)
        
        for i, chunk in enumerate(chunks):
            try:
                # Random delay between 2 and 5 seconds to bypass bot detection
                time.sleep(random.uniform(2.1, 4.8))
                
                headers = {'User-Agent': random.choice(DataPipeline._user_agents)}
                
                # Fetching chunk
                data = yf.download(
                    chunk,
                    period="2y",
                    interval="1d",
                    group_by='ticker',
                    auto_adjust=True,
                    progress=False,
                    threads=False, # Disable threading inside download to reduce concurrent hits
                    session=DataPipeline._session,
                    headers=headers,
                    timeout=20
                )
                
                if not data.empty:
                    all_dfs.append(data)
                
                # Report progress periodically
                if i % 10 == 0:
                    print(f"Progress: {((i/total_chunks)*100):.1f}% complete...")

            except Exception as e:
                print(f"Failed chunk {i}: {e}")
                # If we get blocked, wait longer
                time.sleep(10)
                continue
        
        return pd.concat(all_dfs, axis=1) if all_dfs else None
