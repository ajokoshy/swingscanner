import streamlit as st
from data_fetcher import DataPipeline
from engine_pro import TradingEngine
from database_manager import init_db, SessionLocal, ProScanResult

init_db()

# Main Scanner Logic
def run_market_scan():
    # Use a real list of NSE500 or NIFTY200 symbols
    symbols = ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "TATASTEEL", "TITAN", "SBIN"] 
    
    st.write(f"🔄 Starting Institutional Scan for {len(symbols)} stocks...")
    data_map = DataPipeline.fetch_batch(symbols)
    
    db = SessionLocal()
    for sym, df in data_map.items():
        engine = TradingEngine(df)
        score, reasons = engine.get_score()
        
        if score >= 70:
            levels = engine.get_risk_levels()
            res = ProScanResult(
                symbol=sym, score=score, setup_type=", ".join(reasons),
                entry=levels['entry'], stop_loss=levels['stop_loss'],
                target1=levels['target1'], regime="BULLISH"
            )
            db.add(res)
    db.commit()
    st.success("Scan Complete! Database Updated.")

# Streamlit UI
st.title("🛡️ Pro NSE Swing Scanner")
if st.button("🚀 Run Institutional Scan"):
    run_market_scan()

# Display logic here...