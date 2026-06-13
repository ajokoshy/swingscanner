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
from database_manager import init_db, engine as db_engine, ProScanResult

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
    sorted_setups = sorted(setups, key=lambda x: x['score'], reverse=True)
    
    for s in sorted_setups:
        html += f"<tr><td style='padding: 8px;'><b>{s['symbol']}</b></td><td style='padding: 8px;'>{s['score']}</td><td style='padding: 8px;'>{s['setup_type']}</td><td style='padding: 8px;'>₹{s['entry']}</td><td style='padding: 8px;'>₹{s['target_1']}</td><td style='padding: 8px;'>{s['risk_reward']}</td></tr>"
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
        # Step 0: Ensure tables exist
        init_db()
        today = datetime.now(timezone.utc).date()
        
        # 1. NUCLEAR MAINTENANCE (PURE CORE)
        # Talking directly to the Engine bypasses the SQLAlchemy Session layer entirely.
        # This wipes the collisions for 'June 13' and 'Today' to ensure a fresh, successful scan.
        print(f"Maintenance: Purging collisions for {today} and June 13th...")
        with db_engine.begin() as conn:
            conn.execute(text("DELETE FROM pro_scans_v2 WHERE scan_date = '2026-06-13'"))
            conn.execute(text("DELETE FROM pro_scans_v2 WHERE scan_date = :d"), {"d": today})

        # 2. HIGH SPEED DATA FETCH
        symbols = DataPipeline.get_nse500_symbols()
        symbols = [s.strip() for s in symbols if s and not s.startswith("DUMMY")]
        
        mkt_df = DataPipeline.fetch_market_data("^NSEI")
        mid_df = DataPipeline.fetch_market_data("^NSEMDCP50")
        
        if mkt_df is None:
            raise Exception("Market Index data unavailable.")

        all_data = DataPipeline.fetch_batch_data(symbols)
        
        print(f"🚀 Processing {len(symbols)} symbols in memory...")
        analysis_batch = []

        # 3. ANALYSIS LOOP (Pure RAM - No database contact here)
        for sym in symbols:
            try:
                ticker_sym = f"{sym}.NS"
                if ticker_sym not in all_data.columns.get_level_values(0):
                    continue
                
                df = all_data[ticker_sym].dropna()
                if len(df) >= 150:
                    engine = InstitutionalEngine(df, mkt_df, mid_df)
                    score, setup_type, explanation = engine.get_contextual_score()
                    
                    if score >= 70:
                        levels = RiskManager.get_levels(df)
                        if levels:
                            # IMPORTANT: Store as a DICTIONARY, NOT a ProScanResult object.
                            # This ensures SQLAlchemy doesn't 'track' it and cause a crash.
                            analysis_batch.append({
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

        # 4. DIRECT BATCH UPSERT (Session-less)
        if analysis_batch:
            print(f"Directly saving {len(analysis_batch)} setups to database...")
            # We use the raw Core insert command with the Postgres 'ON CONFLICT' rule
            stmt = pg_upsert(ProScanResult).values(analysis_batch)
            stmt = stmt.on_conflict_do_nothing(index_elements=['symbol', 'scan_date'])
            
            with db_engine.begin() as conn:
                # SQLAlchemy's Core engine handles the batch list instantly
                conn.execute(stmt)
        
        # 5. FETCH RECENT RESULTS AND EMAIL
        # Use a fresh, clean connection just for reading for the email
        with db_engine.connect() as conn:
            fetch_sql = text("SELECT * FROM pro_scans_v2 WHERE scan_date = :d ORDER BY score DESC")
            final_list = conn.execute(fetch_sql, {"d": today}).mappings().all()
        
        print(f"✅ Success. Found {len(final_list)} active setups.")
        send_email(final_list)
        
    except Exception:
        print("--- FATAL SYSTEM ERROR ---")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    run_automation()
