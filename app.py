import streamlit as st
from data_fetcher import DataPipeline
from engine_pro import InstitutionalEngine
from trading_manager import RiskManager
from database_manager import init_db, SessionLocal, ProScanResult
from datetime import datetime

init_db()

st.title("🛡️ Institutional NSE Swing Platform")

if st.sidebar.button("Run NSE500 Full Scan"):
    symbols = DataPipeline.get_nse500_symbols()
    
    # Correct tickers for Yahoo Finance Indices
    mkt_df = DataPipeline.fetch_market_data("^NSEI")       # Nifty 50
    mid_df = DataPipeline.fetch_market_data("^NSEMDCP50") # Nifty Midcap 50
    
    if mkt_df is None or mid_df is None:
        st.error("Could not fetch Market Regime data (Nifty Indices). Scan aborted.")
    else:
        
    db = SessionLocal()
    progress = st.progress(0)
    
    for i, sym in enumerate(symbols[:100]): # Limited to 100 for speed on Render
        df = DataPipeline.fetch_market_data(sym)
        if df is not None and len(df) > 200:
            engine = InstitutionalEngine(df, mkt_df, mid_df)
            score, setup_type, explanation = engine.get_contextual_score()
            
            if score >= 70:
                levels = RiskManager.get_levels(df)
                if levels:
                    # 8. Check for existing scan to avoid duplicates
                    existing = db.query(ProScanResult).filter_by(symbol=sym, scan_date=datetime.utcnow().date()).first()
                    if not existing:
                        res = ProScanResult(
                            symbol=sym, score=score, setup_type=setup_type,
                            market_regime="BULLISH" if score > 70 else "NEUTRAL",
                            entry=levels['entry'], stop_loss=levels['stop_loss'],
                            target_1=levels['t1'], target_2=levels['t2'], target_3=levels['t3'],
                            risk_reward=levels['rr'], explanation=explanation
                        )
                        db.add(res)
        progress.progress((i + 1) / 100)
    db.commit()
    st.success("NSE500 Scan Complete.")

# Display Logic using ProScanResult...
