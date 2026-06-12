import yfinance as yf
import pandas as pd
import io, requests

class DataPipeline:
    @staticmethod
    def get_nse500_symbols():
        """Fetches the official Nifty 500 list from the NSE website."""
        url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        try:
            response = requests.get(url, headers=headers)
            df = pd.read_csv(io.StringIO(response.text))
            return df['Symbol'].tolist()
        except Exception as e:
            print(f"Error fetching NSE500 list: {e}")
            # Fallback to Nifty 50 if the main list fails
            return ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "TATASTEEL", "TITAN", "SBIN"]

    @staticmethod
    def fetch_market_data(symbol, period="2y"):
        """Fetches single index data (Nifty 50, etc). Indices use caret (^) syntax."""
        try:
            df = yf.download(symbol, period=period, interval="1d", progress=False, auto_adjust=True)
            if df.empty: return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df.dropna()
        except Exception:
            return None

    @staticmethod
    def fetch_batch_data(symbols):
        """Downloads all symbols in one single batch request (Institutional Speed)."""
        ns_symbols = [f"{s}.NS" for s in symbols]
        try:
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
