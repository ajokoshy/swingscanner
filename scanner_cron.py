import os
import sys
import traceback
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from data_fetcher import DataPipeline
from engine_pro import InstitutionalEngine
from trading_manager import RiskManager
from database_manager import init_db, SessionLocal, ProScanResult

def send_email(setups):
    sender_email = os.getenv("EMAIL_USER")
    sender_password = os.getenv("EMAIL_PASS")
    receiver_email = os.getenv("RECEIVER_EMAIL")

    if not setups:
        print("No new setups found today. Skipping email.")
        return

    msg = MIMEMultipart()
    msg['Subject'] = f"🚀 NSE Swing Report: {datetime.now().date()}"
    msg['From'] = f"NSE Pro Scanner <{sender_email}>"
    msg['To'] = receiver_email

    html = f"<h3>Top Institutional Swing Setups ({len(setups)})</h3>"
    html += "<table border='1' style='border-collapse: collapse; width: 100%;'>"
    html += "<tr style='background-color: #f2f2f2;'><th>Symbol</th><th>Score</th><th>Setup</th><th>Entry</th><th>Target 1</th><th>RR</th></tr>"
    
    for s in setups:
        html += f"<tr><td><b>{s['symbol']}</b></td><td>{s['score']}</td><td>{s['type']}</td><td>₹{s['entry']}</td><td>₹{s['t1']}</td><td>{s['rr']}</td></tr>"
    html += "</table><p>Visit your dashboard for full analysis and stop loss levels.</p>"
    
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
        print("Database initialized.")
        
        symbols = DataPipeline.get_nse500_symbols()
        print(f"Fetched {len(symbols)} symbols.")
        
        mkt_df = DataPipeline.fetch_market_data("^NSEI")
        mid_df = DataPipeline.fetch_market_data("^NSEMDCP50")
        
        if mkt_df is None:
            raise Exception("Failed to fetch Nifty 50 Index data.")

        all_data = DataPipeline.fetch_batch_data(symbols)
        if all_data is None:
            raise Exception("Batch data download failed.")

        db = SessionLocal()
        email_setups = []
        today = datetime.now(timezone.utc).date()

        for sym in symbols:
            try:
                ticker_sym = f"{sym}.NS"
                if ticker_sym not in all_data.columns.get_level_values(0):
                    continue
                
                df = all_data[ticker_sym].dropna()
                
                if len(df) >= 200:
                    engine = InstitutionalEngine(df, mkt_df, mid_df)
                    score, setup_type, explanation = engine.get_contextual_score()
                    
                    if score >= 70:
                        levels = RiskManager.get_levels(df)
                        if levels:
                            # DUPLICATE CHECK: Skip if symbol already scanned today
                            existing = db.query(ProScanResult).filter_by(
                                symbol=sym, 
                                scan_date=today
                            ).first()
                            
                            if not existing:
                                res = ProScanResult(
                                    symbol=sym, score=score, setup_type=setup_type,
                                    market_regime="BULLISH" if score > 75 else "NEUTRAL", 
                                    entry=levels['entry'],
                                    stop_loss=levels['stop_loss'], target_1=levels['t1'],
                                    target_2=levels['t2'], target_3=levels['t3'],
                                    risk_reward=levels['rr'], explanation=explanation
                                )
                                db.add(res)
                                email_setups.append({
                                    'symbol': sym, 'score': score, 'type': setup_type, 
                                    'entry': levels['entry'], 't1': levels['t1'], 'rr': levels['rr']
                                })
            except Exception as e:
                # Log error for specific stock but continue the loop
                print(f"Error processing {sym}: {e}")
                continue

        db.commit()
        db.close()
        print(f"Scan successful. Saved {len(email_setups)} new setups.")
        send_email(email_setups)
        
    except Exception as e:
        print("--- CRITICAL ERROR DURING SCAN ---")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    run_automation()
