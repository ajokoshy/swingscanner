import os
import sys
import traceback
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_upsert
from data_fetcher import DataPipeline
from engine_pro import InstitutionalEngine
from trading_manager import RiskManager
from database_manager import init_db, engine as db_engine, ProScanResult, SessionLocal

def send_email(setups):
    sender_email = os.getenv("EMAIL_USER")
    sender_password = os.getenv("EMAIL_PASS")
    receiver_email = os.getenv("RECEIVER_EMAIL")
    if not setups:
        print("No new elite setups found. Email skipped.")
        return

    msg = MIMEMultipart()
    msg['Subject'] = f"🚀 NSE Swing Report: {datetime.now(timezone.utc).date()}"
    msg['From'] = f"NSE Pro Scanner <{sender_email}>"
    msg['To'] = receiver_email

    html = f"<h3>Institutional Swing Setups Found Today ({len(setups)})</h3>"
    html += "<table border='1' style='border-collapse: collapse; width: 100%; font-family: sans-serif;'>"
    html += "<tr style='background-color: #004a99; color: white;'><th>Symbol</th><th>Score</th><th>Setup</th><th>Entry</th><th>Target 1</th><th>RR</th></tr>"
    
    # Sort for professional presentation
    sorted_setups = sorted(setups, key=lambda x: x.score, reverse=True)
    
    for s in sorted_setups:
        html += f"<tr><td style='padding: 8px;'><b>{s.symbol}</b></td><td style='padding: 8px;'>{s.score}</td><td style='padding: 8px;'>{s.setup_type}</td><td style='padding: 8px;'>₹{s.entry}</td><td style='padding: 8px;'>₹{s.target_1}</td><td style='padding: 8px;'>{s.risk_reward}</td></tr>"
    html += "</table><p>Visit your dashboard for full ATR analysis and Stop Loss levels.</p>"
    msg.attach(MIMEText(html, 'html'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        print("✅ Email report sent.")
    except Exception as e:
        print(f"❌ Email failed: {e}")

def run_automation():
    try:
        init_db()
        today = datetime.now(timezone.utc).date()
        
        # 1. CLEANUP (PURE CORE): Clear previous collisions
        # We talk directly to the Engine, bypassing the 'Session' entirely.
        print(f"Maintenance: Purging collisions for {today} and June 13th...")
        with db_engine.begin() as conn:
            conn.execute(text("DELETE FROM pro_scans_v2 WHERE scan_date = :d OR scan_date = '2026-06-13'"), {"d": today})

        # 2. DATA ACQUISITION
        symbols = DataPipeline.get_nse500_symbols()
        symbols = [s.strip() for s in symbols if s and not s.startswith("DUMMY")]
        mkt_df = DataPipeline.fetch_market_data("^NSEI")
        mid_df = DataPipeline.fetch_market_data("^NSEMDCP50")
        all_data = DataPipeline.fetch_batch_data(symbols)
        
        print(f"🚀 Processing {len(symbols)} symbols in memory...")
        batch_results = []

        # 3. ANALYSIS (Pure Python Dictionaries)
        for sym in symbols:
            try:
                ticker_sym = f"{sym}.NS"
                if ticker_sym not in all_data.columns.get_level_values(0): continue
                
                df = all_data[ticker_sym].dropna()
                if len(df) >= 150:
                    engine = InstitutionalEngine(df, mkt_df, mid_df)
                    score, setup_type, explanation = engine.get_contextual_score()
                    
                    if score >= 70:
                        levels = RiskManager.get_levels(df)
                        if levels:
                            # We create a simple DICT, NOT a ProScanResult object.
                            # This ensures SQLAlchemy doesn't 'track' it.
                            batch_results.append({
                                "symbol": sym,
                                "scan_date": today,
                                "score": int(score),
                                "setup_type": setup_type,
                                "market_regime": "BULLISH" if score > 75 else "NEUTRAL",
                                "entry": float(levels['entry']),
                                "stop_loss": float(levels['stop_loss']),
                                "target_1": float(levels['t1']),
                                "target_2": float(levels['t2']),
                                "target_3": float(levels['t3']),
                                "risk_reward": float(levels['rr']),
                                "explanation": str(explanation)
                            })
            except Exception:
                continue

        # 4. PURE CORE BATCH UPSERT (Session-less)
        if batch_results:
            print(f"Directly saving {len(batch_results)} setups to database...")
            # Core insert command with Postgres 'ON CONFLICT DO NOTHING' rule
            stmt = pg_upsert(ProScanResult).values(batch_results)
            stmt = stmt.on_conflict_do_nothing(index_elements=['symbol', 'scan_date'])
            
            with db_engine.begin() as conn:
                conn.execute(stmt)
        
        # 5. FETCH RECENT RESULTS AND EMAIL (Fresh Session for Read Only)
        db = SessionLocal()
        final_list = db.query(ProScanResult).filter_by(scan_date=today).order_by(ProScanResult.score.desc()).all()
        db.close()
        
        print(f"✅ Success. Found {len(final_list)} setups.")
        send_email(final_list)
        
    except Exception:
        print("--- FATAL SYSTEM ERROR ---")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    run_automation()
