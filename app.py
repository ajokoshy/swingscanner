import streamlit as st
from data_fetcher import DataPipeline
from engine_pro import InstitutionalEngine
from trading_manager import RiskManager
from database_manager import init_db, SessionLocal, ProScanResult
from datetime import datetime

# Initialize DB Tables
init_db()

st.set_page_config(page_title="🛡️ Institutional NSE Swing Platform", layout="wide")

# --- SIDEBAR: SCANNER CONTROL ---
st.sidebar.title("Trading Controls")
if st.sidebar.button("🚀 Run Full NSE500 Scan"):
    symbols = DataPipeline.get_nse500_symbols()
    
    # 1. Fetch Regime Data (Indices)
    # Note: No .NS for indices
    mkt_df = DataPipeline.fetch_market_data("^NSEI")
    mid_df = DataPipeline.fetch_market_data("^NSEMDCP50")
    
    if mkt_df is None:
        st.error("Market data unavailable. Please try again.")
    else:
        st.info(f"Downloading data for {len(symbols)} stocks...")
        all_data = DataPipeline.fetch_batch_data(symbols)
        
        if all_data is None:
            st.error("Batch download failed.")
        else:
            db = SessionLocal()
            progress = st.progress(0)
            status_text = st.empty()
            found_count = 0
            today = datetime.utcnow().date()

            # 2. Process Data Locally (Fast)
            for i, sym in enumerate(symbols):
                ticker_sym = f"{sym}.NS"
                try:
                    # Extract individual stock from batch
                    df = all_data[ticker_sym].dropna()
                    
                    if len(df) > 200:
                        # Institutional Analysis
                        engine = InstitutionalEngine(df, mkt_df, mid_df)
                        score, setup_type, explanation = engine.get_contextual_score()
                        
                        # Apply Institutional Threshold
                        if score >= 70:
                            # ATR Risk Check
                            levels = RiskManager.get_levels(df)
                            
                            if levels:
                                # Prevent Duplicate Entry for Today
                                existing = db.query(ProScanResult).filter_by(
                                    symbol=sym, scan_date=today
                                ).first()
                                
                                if not existing:
                                    res = ProScanResult(
                                        symbol=sym,
                                        score=score,
                                        setup_type=setup_type,
                                        market_regime="BULLISH" if score > 75 else "NEUTRAL",
                                        entry=levels['entry'],
                                        stop_loss=levels['stop_loss'],
                                        target_1=levels['t1'],
                                        target_2=levels['t2'],
                                        target_3=levels['t3'],
                                        risk_reward=levels['rr'],
                                        explanation=explanation
                                    )
                                    db.add(res)
                                    found_count += 1
                except Exception:
                    continue # Skip tickers with corrupted data
                
                # Update UI
                if i % 10 == 0:
                    status_text.text(f"Analyzing {sym}... ({i+1}/{len(symbols)})")
                    progress.progress((i + 1) / len(symbols))
            
            db.commit()
            db.close()
            status_text.text(f"Scan Complete! Found {found_count} setups.")
            st.success(f"Full NSE500 Scan Successful.")

# --- MAIN UI: DASHBOARD ---
st.title("🛡️ Institutional NSE Swing Platform")

db = SessionLocal()
try:
    # Pull current setups (Latest Scans)
    today = datetime.utcnow().date()
    results = db.query(ProScanResult).filter(
        ProScanResult.scan_date == today
    ).order_by(ProScanResult.score.desc()).all()

    if not results:
        st.info("No active setups for today. Showing latest available results.")
        results = db.query(ProScanResult).order_by(
            ProScanResult.scan_date.desc(), 
            ProScanResult.score.desc()
        ).limit(15).all()

    if results:
        st.subheader(f"🎯 Top Opportunities ({len(results)})")
        for res in results:
            # Color coding for ELITE setups
            header = f"⭐ {res.symbol} | Score: {res.score}/100 | {res.setup_type}"
            if res.score >= 85: header = "🔥 [ELITE] " + header
            
            with st.expander(header):
                c1, c2, c3 = st.columns([1, 1, 1.5])
                with c1:
                    st.write("**Trade Levels**")
                    st.code(f"Entry: ₹{res.entry}")
                    st.code(f"Stop:  ₹{res.stop_loss}")
                    st.write(f"**R:R:** {res.risk_reward}")
                with c2:
                    st.write("**Targets**")
                    st.success(f"Target 1: ₹{res.target_1}")
                    st.success(f"Target 2: ₹{res.target_2}")
                    st.success(f"Target 3: ₹{res.target_3}")
                with c3:
                    st.write("**Analysis Factors**")
                    for point in res.explanation.split(" | "):
                        st.write(f"✅ {point}")
                    st.caption(f"Scanned: {res.scan_date} | Regime: {res.market_regime}")
    else:
        st.warning("Database is empty. Run a 'Full Scan' from the sidebar to populate.")
finally:
    db.close()
