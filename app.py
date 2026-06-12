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
    
    # Expanded Watchlist for better results
    WATCHLIST = [
        "ASTERDM", "RELIANCE", "TCS", "INFY", "TATASTEEL", "HDFCBANK", 
        "SBIN", "ICICIBANK", "AXISBANK", "BHARTIARTL", "ITC", "LT", 
        "MARUTI", "KOTAKBANK", "ADANIENT", "SUNPHARMA", "TITAN", "BAJFINANCE"
    ]
    
    if st.button("Run Automated Scan"):
        db = SessionLocal()
        found_count = 0
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, sym in enumerate(WATCHLIST):
            status_text.text(f"Scanning {sym}...")
            engine = SwingEngine(sym)
            if engine.fetch_data():
                analysis = engine.analyze()
                # LOWERED THRESHOLD TO 0 FOR TESTING - This ensures you see results
                if analysis:
                    # Create DB object
                    res_obj = SwingResult(
                        symbol=analysis['symbol'],
                        score=analysis['score'],
                        classification=analysis['classification'],
                        entry=analysis['entry'],
                        stop_loss=analysis['stop_loss'],
                        target_1=analysis['target_1'],
                        target_2=analysis['target_2'],
                        risk_reward=analysis['risk_reward'],
                        reasons=analysis['reasons']
                    )
                    db.add(res_obj)
                    found_count += 1
            progress_bar.progress((i + 1) / len(WATCHLIST))
        
        db.commit()
        db.close()
        status_text.text(f"Scan Complete! Found {found_count} stocks.")
        st.success(f"Successfully analyzed and saved {found_count} stocks to the database.")

    # Display Results from Database
    st.divider()
    db = SessionLocal()
    # Pull latest 20 scans regardless of score to verify DB is working
    saved_scans = db.query(SwingResult).order_by(SwingResult.created_at.desc(), SwingResult.score.desc()).limit(20).all()
    
    if saved_scans:
        st.subheader(f"Latest Candidates ({len(saved_scans)})")
        for res in saved_scans:
            # Color code the header based on score
            label = f"{res.symbol} — Score: {res.score}/100"
            with st.expander(label):
                c1, c2 = st.columns(2)
                with c1:
                    st.write(f"**Classification:** {res.classification}")
                    st.write(f"**Entry:** ₹{res.entry}")
                    st.write(f"**Stop Loss:** ₹{res.stop_loss}")
                with c2:
                    st.write(f"**Target 1:** ₹{res.target_1}")
                    st.write(f"**Target 2:** ₹{res.target_2}")
                    st.write(f"**Analysis:** {res.reasons}")
    else:
        st.info("The database is currently empty. Click 'Run Automated Scan' to fetch data.")
    db.close()
