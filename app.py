import streamlit as st
from database import init_db, SessionLocal, SwingResult
from engine import SwingEngine
from datetime import datetime

st.set_page_config(page_title="NSE Swing Scanner", layout="wide")
init_db()

st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ["Individual Analysis", "Daily Market Scanner"])

# --- PAGE 1: INDIVIDUAL ANALYSIS ---
if page == "Individual Analysis":
    st.title("🔍 Stock Analysis")
    symbol = st.text_input("Enter NSE Stock Symbol (e.g., ASTERDM, RELIANCE)", "").upper()

    if symbol:
        engine = SwingEngine(symbol)
        with st.spinner(f"Analyzing {symbol}..."):
            if engine.fetch_data():
                data = engine.analyze()
                if data:
                    col1, col2, col3 = st.columns([1,1,2])
                    
                    with col1:
                        st.metric("Swing Score", f"{data['score']}/100")
                        st.subheader(data['classification'])
                    
                    with col2:
                        st.write("**Trade Setup**")
                        st.write(f"Entry: `{data['entry']}`")
                        st.write(f"Stop Loss: `{data['stop_loss']}`")
                        st.write(f"Target 1: `{data['target_1']}`")
                        st.write(f"Target 2: `{data['target_2']}`")
                        st.write(f"RR: `{data['risk_reward']}`")

                    with col3:
                        st.write("**Analysis Details**")
                        for reason in data['reasons'].split(", "):
                            st.write(f"✅ {reason}")
                else:
                    st.error("Insufficient data for analysis.")
            else:
                st.error("Stock not found.")

# --- PAGE 2: MARKET SCANNER ---
elif page == "Daily Market Scanner":
    st.title("📊 Top Swing Opportunities")
    
    # Simple list for demo; in production, load 500 stocks from a CSV
    WATCHLIST = ["ASTERDM", "RELIANCE", "TCS", "INFY", "TATASTEEL", "HDFCBANK", "SBIN", "ICICIBANK"]
    
    if st.button("Run Automated Scan"):
        db = SessionLocal()
        results = []
        progress_bar = st.progress(0)
        
        for i, sym in enumerate(WATCHLIST):
            engine = SwingEngine(sym)
            if engine.fetch_data():
                analysis = engine.analyze()
                if analysis and analysis['score'] >= 70:
                    # Save to DB
                    res_obj = SwingResult(**analysis)
                    db.add(res_obj)
                    results.append(analysis)
            progress_bar.progress((i + 1) / len(WATCHLIST))
        
        db.commit()
        db.close()
        st.success("Scan Complete!")

    # Display Results from Database
    db = SessionLocal()
    saved_scans = db.query(SwingResult).order_by(SwingResult.score.desc()).limit(10).all()
    
    if saved_scans:
        for res in saved_scans:
            with st.expander(f"Rank: {res.symbol} - Score: {res.score}"):
                c1, c2 = st.columns(2)
                c1.write(f"**Entry:** {res.entry} | **SL:** {res.stop_loss}")
                c1.write(f"**Targets:** {res.target_1}, {res.target_2}")
                c2.write(f"**Reasons:** {res.reasons}")
    else:
        st.info("No scans found. Click 'Run Automated Scan' above.")