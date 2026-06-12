import yfinance as yf
import pandas as pd
import io, requests

class DataPipeline:
    # 9. AUTOMATED NSE500 UNIVERSE LOADING
    @staticmethod
    def get_nse500_symbols():
        try:
            url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers)
            df = pd.read_csv(io.StringIO(response.text))
            return df['Symbol'].tolist()
        except:
            return ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "TATASTEEL"]

    @staticmethod
    def fetch_market_data(symbol, period="2y"):
        sym = f"{symbol}.NS" if not symbol.endswith(".NS") else symbol
        df = yf.download(sym, period=period, interval="1d", progress=False, auto_adjust=True)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        return df.dropna()