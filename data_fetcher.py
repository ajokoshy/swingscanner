import yfinance as yf
import pandas as pd
import io, requests

class DataPipeline:
    @staticmethod
    def get_nse500_symbols():
        try:
            url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers)
            df = pd.read_csv(io.StringIO(response.text))
            return df['Symbol'].tolist()
        except Exception as e:
            print(f"Error fetching NSE500 list: {e}")
            # Fallback to a small list if NSE website is down
            return ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY"]

    @staticmethod
    def fetch_market_data(symbol, period="2y"):
        # INDEX FIX: Symbols starting with '^' do not get '.NS'
        if symbol.startswith("^"):
            sym = symbol 
        else:
            sym = f"{symbol}.NS" if not symbol.endswith(".NS") else symbol
            
        try:
            df = yf.download(sym, period=period, interval="1d", progress=False, auto_adjust=True)
            
            if df.empty:
                print(f"Warning: No data found for {sym}")
                return None
                
            # Flatten MultiIndex if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # Clean data: Remove any rows with NaN in critical columns
            df = df.dropna(subset=['Close'])
            
            return df
        except Exception as e:
            print(f"Error downloading {sym}: {e}")
            return None
