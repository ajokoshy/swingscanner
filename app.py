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
