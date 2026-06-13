import os
import sys
import traceback
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import insert  # Required for Upsert
from data_fetcher import DataPipeline
from engine_pro import InstitutionalEngine
from trading_manager import RiskManager
from database_manager import init_db, SessionLocal, ProScanResult

def send_email(setups):
    sender_email = os.getenv("EMAIL_USER")
    sender_password = os.getenv("EMAIL_PASS")
    receiver_email = os.getenv("RECEIVER_EMAIL")

    if not setups:
        print("No new elite setups found for this scan. Skipping email.")
        return

    msg = MIMEMultipart()
    msg['Subject'] = f"🚀 NSE Swing Report: {datetime.now(timezone.utc).date()}"
    msg['From'] = f"NSE Pro Scanner <{sender_email}>"
    msg['To'] = receiver_email

    html = f"<h3>Top Institutional Swing Setups ({len(setups)})</h3>"
    html += "<table border='1' style='border-collapse: collapse; width: 100%; font-family: sans-serif;'>"
    html += "<tr style='background-color: #004a99; color: white;'><th>Symbol</th><th>Score</th><th>Setup</th><th>Entry</th><th>Target 1</th><th>RR</th></tr>"
    
    for s in setups:
        html += f"<tr><td style='padding: 8px;'><b>{s['symbol']}</b></td><td style='padding: 8px;'>{s['score']}</td><td style='padding: 8px;'>{s['type']}</td><td style='padding: 8px;'>₹{s['entry']}</td><td style='padding: 8px;'>₹{s['t1']}</td><td style='padding: 8px;'>{s['rr']}</td></tr>"
    html += "</table><p>Open your Dashboard for full analysis and ATR-based stop loss levels.</p>"
    
    msg.attach(MIMEText(html, 'html'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        print("Email sent successfully.")
    except Exception as e:
        print(f"Failed to send email: {e}")

def run_automation():
    try:
        init_db()
        print("Connecting to Market Data...")
        
        symbols = DataPipeline.get_nse500_symbols()
        mkt_df = DataPipeline.fetch_market_data("^NSEI")
        mid_df = DataPipeline.fetch_market_data("^NSEMDCP50")
        
        if mkt_df is None:
            raise Exception("Regime Data (Nifty 50) Unavailable.")

        all_data = DataPipeline.fetch_batch_data(symbols)
        if all_data is None:
            raise Exception("Market Batch Download Failed.")

        db = SessionLocal()
        email_setups = []
        today = datetime.now(timezone.utc).date()

        print(f"Analyzing {len(symbols)} symbols...")
        for sym in symbols:
            try:
                ticker_sym = f"{sym}.NS"
                if ticker_sym not in all_data.columns.get_level_values(0):
                    continue
                
                df = all_data[ticker_sym].dropna()
                
                if len(df) >= 200:
                    engine = InstitutionalEngine(df, mkt_df, mid_df)
                    score, setup_type, explanation = engine.get_contextual_score()
                    
                    if score >= 75: # High quality threshold for email alerts
                        levels = RiskManager.get_levels(df)
                        if levels:
                            # PREPARE DATA DICTIONARY
                            data_dict = {
                                "symbol": sym,
                                "scan_date": today,
                                "score": score,
                                "setup_type": setup_type,
                                "market_regime": "BULLISH" if score > 75 else "NEUTRAL",
                                "entry": levels['entry'],
                                "stop_loss": levels['stop_loss'],
                                "target_1": levels['t1'],
                                "target_2": levels['t2'],
                                "target_3": levels['t3'],
                                "risk_reward": levels['rr'],
                                "explanation": explanation
                            }

                            # 1. INSTITUTIONAL UPSERT (INSERT OR IGNORE)
                            # This prevents the UniqueViolation crash completely
                            stmt = insert(ProScanResult).values(data_dict)
                            stmt = stmt.on_conflict_do_nothing(index_elements=['symbol', 'scan_date'])
                            
                            result = db.execute(stmt)
                            
                            # result.rowcount is 1 if it's a new entry, 0 if it was a duplicate
                            if result.rowcount > 0:
                                email_setups.append({
                                    'symbol': sym, 'score': score, 'type': setup_type, 
                                    'entry': levels['entry'], 't1': levels['t1'], 'rr': levels['rr']
                                })
            except Exception:
                continue

        db.commit()
        db.close()
        print(f"Scan Finished. Found {len(email_setups)} new setups.")
        send_email(email_setups)
        
    except Exception:
        print("--- CRITICAL SYSTEM ERROR ---")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    run_automation()
