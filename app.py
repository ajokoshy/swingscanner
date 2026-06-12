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
    
    # 1. Fetch Regime Data
    mkt_df = DataPipeline.fetch_market_data("^NSEI")
    mid_df = DataPipeline.fetch_market_data("^NSEMDCP50")
    
    if mkt_df is None or mid_df is None:
        st.error("Could not fetch Market Regime data (Nifty Indices). Scan aborted.")
    else:
        # --- EVERYTHING BELOW MUST BE INDENTED ---
        db = SessionLocal()
        progress = st.progress(0)
        status_text = st.empty()
        found_count = 0
        
        # Limit symbols for testing speed, or remove [:100] for full NSE500
        scan_list = symbols[:100] 
        
        for i, sym in enumerate(scan_list):
            status_text.text(f"Scanning {sym} ({i+1}/{len(scan_list)})...")
            df = DataPipeline.fetch_market_data(sym)
            
            if df is not None and len(df) > 200:
                # 2. Institutional Scoring
                engine = InstitutionalEngine(df, mkt_df, mid_df)
                score, setup_type, explanation = engine.get_contextual_score()
                
                # 3. Quality Threshold
                if score >= 70:
                    # 4. Risk & Setup Logic (ATR Bug fixed here)
                    levels = RiskManager.get_levels(df)
                    
                    if levels:
                        # 5. Prevent Duplicates for the same day
                        today = datetime.utcnow().date()
                        existing = db.query(ProScanResult).filter_by(
                            symbol=sym, 
                            scan_date=today
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
            
            # Update UI Progress
            progress.progress((i + 1) / len(scan_list))
        
        db.commit()
        db.close()
        status_text.text(f"Scan Complete! Found {found_count} setups.")
        st.success(f"Analyzed {len(scan_list)} stocks. Check results below.")
# Display Logic using ProScanResult...
# --- DATABASE DISPLAY LOGIC ---
st.divider()
st.subheader("🎯 Active Institutional Setups")

db = SessionLocal()
try:
    # Query the latest scans from the database
    # We sort by date (newest first) and then by score (highest first)
    today = datetime.utcnow().date()
    results = db.query(ProScanResult).filter(
        ProScanResult.scan_date == today
    ).order_by(ProScanResult.score.desc()).all()

    if not results:
        # Fallback: Show yesterday's results if today's scan hasn't run
        st.info("No scans found for today. Showing most recent historical results.")
        results = db.query(ProScanResult).order_by(
            ProScanResult.scan_date.desc(), 
            ProScanResult.score.desc()
        ).limit(10).all()

    if results:
        for res in results:
            # Create a professional card for each stock
            with st.expander(f"⭐ {res.symbol} | Score: {res.score}/100 | {res.setup_type}"):
                col1, col2, col3 = st.columns([1, 1, 1.5])
                
                with col1:
                    st.write("**Trade Levels**")
                    st.write(f"Entry: `₹{res.entry}`")
                    st.write(f"Stop Loss: `₹{res.stop_loss}`")
                    st.write(f"Risk Reward: `{res.risk_reward}`")
                
                with col2:
                    st.write("**Targets**")
                    st.success(f"T1: ₹{res.target_1}")
                    st.success(f"T2: ₹{res.target_2}")
                    st.success(f"T3: ₹{res.target_3}")
                
                with col3:
                    st.write("**Institutional Analysis**")
                    # Split the explanation string back into clean bullet points
                    for point in res.explanation.split(" | "):
                        st.write(f"🔹 {point}")
                    st.caption(f"Scan Date: {res.scan_date} | Regime: {res.market_regime}")
    else:
        st.warning("No setups found in database. Please run a 'Full Scan' from the sidebar.")

finally:
    db.close()
