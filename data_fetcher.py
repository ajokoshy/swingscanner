import re
import yfinance as yf
import pandas as pd
import io, requests
import time

class DataPipeline:
    @staticmethod
    def get_nse500_symbols():
        url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            response = requests.get(url, headers=headers, timeout=15)
            df = pd.read_csv(io.StringIO(response.text))
            
            # YOUR MOD: Strip and Regex for symbols like M&M
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
        """Resilient fetch for index data (^NSEI) with retries."""
        sym = symbol if symbol.startswith("^") else f"{symbol}.NS"
        
        for attempt in range(3):
            try:
                # Indices often work better with auto_adjust=False on Yahoo
                df = yf.download(sym, period=period, interval="1d", progress=False, auto_adjust=False)
                
                if df is not None and not df.empty and len(df) > 10:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    return df.dropna(subset=['Close'])
                time.sleep(1)
            except Exception:
                time.sleep(1)
        return None

    @staticmethod
    def fetch_batch_data(symbols):
        """High-speed batch download."""
        ns_symbols = [f"{s}.NS" for s in symbols]
        try:
            data = yf.download(
                ns_symbols,
                period="2y",
                interval="1d",
                group_by='ticker',
                auto_adjust=True,
                progress=False,
                threads=True,
                timeout=30
            )
            return data
        except Exception as e:
            print(f"Batch fetch error: {e}")
            return None
