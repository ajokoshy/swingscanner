import streamlit as st
from data_fetcher import DataPipeline
from engine_pro import InstitutionalEngine
from trading_manager import RiskManager
from database_manager import init_db, SessionLocal, ProScanResult
from datetime import datetime, timezone

# 1. INITIALIZE DATABASE
# Creates tables in Neon if they don't exist
init_db()

st.set_page_config(
    page_title="🛡️ Institutional NSE Swing Platform", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- SIDEBAR: SCANNER CONTROL ---
st.sidebar.title("Trading Controls")
st.sidebar.markdown("---")
st.sidebar.info("The scanner analyzes the Nifty 500 universe using an institutional multi-factor model.")

if st.sidebar.button("🚀 Run Full NSE500 Scan"):
    symbols = DataPipeline.get_nse500_symbols()
    
    # Fetch Market Context (Indices)
    mkt_df = DataPipeline.fetch_market_data("^NSEI")
    mid_df = DataPipeline.fetch_market_data("^NSEMDCP50")
    
    if mkt_df is None:
        st.error("Market data unavailable. Check internet connection.")
    else:
        st.info(f"Downloading batch data for {len(symbols)} stocks...")
        all_data = DataPipeline.fetch_batch_data(symbols)
        
        if all_data is None:
            st.error("Batch download failed. Yahoo Finance might be rate-limiting.")
        else:
            db = SessionLocal()
            progress = st.progress(0)
            status_text = st.empty()
            new_count = 0
            skipped_count = 0
            
            # Modern UTC Date handling
            today = datetime.now(timezone.utc).date()

            # Process all stocks in the Nifty 500
            for i, sym in enumerate(symbols):
                ticker_sym = f"{sym}.NS"
                try:
                    # Robust extraction from batch
                    if ticker_sym not in all_data.columns.get_level_values(0):
                        continue
                        
                    df = all_data[ticker_sym].dropna()
                    
                    if len(df) >= 200:
                        # Step 1: Score the stock
                        engine = InstitutionalEngine(df, mkt_df, mid_df)
                        score, setup_type, explanation = engine.get_contextual_score()
                        
                        # Step 2: Quality Gate (70+)
                        if score >= 70:
                            # Step 3: Risk & Target Calculation
                            levels = RiskManager.get_levels(df)
                            
                            if levels:
                                # Step 4: Duplicate Prevention Logic
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
                                    new_count += 1
                                else:
                                    skipped_count += 1
                except Exception:
                    continue
                
                # Visual UI updates
                if i % 10 == 0:
                    status_text.text(f"Processing {sym} ({i+1}/{len(symbols)})...")
                    progress.progress((i + 1) / len(symbols))
            
            db.commit()
            db.close()
            status_text.text(f"✅ Scan Complete!")
            st.sidebar.success(f"New: {new_count} | Existing: {skipped_count}")
            st.balloons()

# --- MAIN UI: DASHBOARD ---
st.title("🛡️ Institutional NSE Swing Platform")
st.markdown(f"**Market Status:** Analysis based on latest Nifty 50 Close.")

db = SessionLocal()
try:
    # Modern UTC date for database query
    today = datetime.now(timezone.utc).date()
    
    # Query today's results
    results = db.query(ProScanResult).filter(
        ProScanResult.scan_date == today
    ).order_by(ProScanResult.score.desc()).all()

    # Fallback to historical if today's scan hasn't run yet
    if not results:
        st.info("No new setups scanned today yet. Showing latest historical results.")
        results = db.query(ProScanResult).order_by(
            ProScanResult.scan_date.desc(), 
            ProScanResult.score.desc()
        ).limit(20).all()

    if results:
        st.subheader(f"🎯 Top Opportunities ({len(results)})")
        
        # Display as cards in an expander
        for res in results:
            # Color coding: Elite setups get a fire emoji
            is_elite = res.score >= 85
            header = f"{'🔥 [ELITE]' if is_elite else '⭐'} {res.symbol} | Score: {res.score}/100 | {res.setup_type}"
            
            with st.expander(header):
                col1, col2, col3 = st.columns([1, 1, 1.5])
                
                with col1:
                    st.write("**📍 Trade Levels**")
                    st.code(f"Entry: ₹{res.entry}")
                    st.code(f"Stop:  ₹{res.stop_loss}")
                    st.write(f"**Risk/Reward:** {res.risk_reward}")
                
                with col2:
                    st.write("**🎯 Profit Targets**")
                    st.success(f"T1: ₹{res.target_1}")
                    st.success(f"T2: ₹{res.target_2}")
                    st.success(f"T3: ₹{res.target_3}")
                
                with col3:
                    st.write("**📊 Analysis Factors**")
                    # Split the explanation string stored in DB into clean bullet points
                    points = res.explanation.split(" | ")
                    for p in points:
                        st.write(f"✅ {p}")
                    st.caption(f"Scanned on: {res.scan_date} | Market Regime: {res.market_regime}")
                    
    else:
        st.warning("The database is currently empty. Please trigger a 'Full Scan' from the sidebar.")

except Exception as e:
    st.error(f"Database Error: {e}")
finally:
    db.close()
