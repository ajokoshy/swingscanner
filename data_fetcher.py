import yfinance as yf
import pandas as pd
import io, requests

class DataPipeline:
    @staticmethod
    def get_nse500_symbols():
        url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            response = requests.get(url, headers=headers)
            df = pd.read_csv(io.StringIO(response.text))
            
            # SANITIZATION: Remove whitespace and filter out non-standard symbols
            symbols = df['Symbol'].str.strip().unique().tolist()
            clean_symbols = [s for s in symbols if s.isalnum() and not s.startswith("DUMMY")]
            
            return clean_symbols
        except Exception as e:
            print(f"Error fetching NSE500 list: {e}")
            return ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY"]

    @staticmethod
    def fetch_market_data(symbol, period="2y"):
        # Index Fix: Do not add .NS to carets
        sym = symbol if symbol.startswith("^") else f"{symbol}.NS"
        try:
            df = yf.download(sym, period=period, interval="1d", progress=False, auto_adjust=True)
            if df.empty: return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df.dropna()
        except Exception:
            return None

    @staticmethod
    def fetch_batch_data(symbols):
        ns_symbols = [f"{s}.NS" for s in symbols]
        try:
            # Batch download with threads enabled
            data = yf.download(
                ns_symbols, 
                period="2y", 
                interval="1d", 
                group_by='ticker', 
                auto_adjust=True, 
                progress=False,
                threads=True
            )
            return data
        except Exception as e:
            print(f"Batch fetch error: {e}")
            return None
