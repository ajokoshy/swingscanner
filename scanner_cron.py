"""
scanner_cron.py  —  SwingScanner v2
Automated daily scan runner (GitHub Actions / any cron).
"""

import logging
import os
import smtplib
import sys
import traceback
from datetime import datetime, timezone, date as date_type
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd
from sqlalchemy import text

from data_fetcher import DataPipeline, refresh_bhavcopy_cache
from database_manager import init_db, engine as db_engine
from engine_pro import InstitutionalEngine
from trading_manager import RiskManager

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("scanner_cron")

SCORE_THRESHOLD = 70
FLUSH_EVERY     = 25
IST_OFFSET_HRS  = 5.5          # UTC + 5:30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

INSERT_SQL = text("""
    INSERT INTO pro_scans_v2
        (symbol, scan_date, score, setup_type, market_regime,
         entry, stop_loss, target_1, target_2, target_3, risk_reward, explanation)
    VALUES
        (:symbol, :scan_date, :score, :setup_type, :market_regime,
         :entry, :stop_loss, :target_1, :target_2, :target_3, :risk_reward, :explanation)
    ON CONFLICT ON CONSTRAINT _symbol_date_uc DO NOTHING
""")


def _flush_batch(batch: list[dict]) -> None:
    if not batch:
        return
    with db_engine.connect() as conn:
        conn.execute(INSERT_SQL, batch)
        conn.commit()
    logger.info("Flushed %d setups to DB.", len(batch))
    batch.clear()


def _synthetic_index() -> pd.DataFrame:
    """
    Fallback when Yahoo blocks index fetches.
    pd.bdate_range from a fixed start guarantees exactly 300 rows
    regardless of what day of the week today falls on.
    """
    all_bdays = pd.bdate_range(start="2010-01-01", end=datetime.now())
    dates = all_bdays[-300:]
    n = len(dates)
    return pd.DataFrame({
        "Open":   [23000 + x * 1.2 for x in range(n)],
        "High":   [23100 + x * 1.2 for x in range(n)],
        "Low":    [22900 + x * 1.2 for x in range(n)],
        "Close":  [23000 + x * 1.2 for x in range(n)],
        "Volume": [0] * n,
    }, index=dates)


def send_email(setups: list, scan_date: date_type) -> None:
    sender_email    = os.getenv("EMAIL_USER")
    sender_password = os.getenv("EMAIL_PASS")
    receiver_email  = os.getenv("RECEIVER_EMAIL")

    if not (sender_email and sender_password and receiver_email):
        logger.warning("Email credentials not set — skipping email.")
        return

    if not setups:
        logger.info("No setups found today — email skipped.")
        return

    sorted_setups = sorted(setups, key=lambda x: x["score"], reverse=True)
    elite_count   = sum(1 for s in sorted_setups if s["score"] >= 85)
    strong_count  = sum(1 for s in sorted_setups if 75 <= s["score"] < 85)

    msg = MIMEMultipart()
    msg["Subject"] = f"NSE Swing Setups — {scan_date} ({len(setups)} found)"
    msg["From"]    = f"NSE Pro Scanner <{sender_email}>"
    msg["To"]      = receiver_email

    rows_html = ""
    for s in sorted_setups:
        bg    = "#fff8e1" if s["score"] >= 85 else ("#f0f7ff" if s["score"] >= 75 else "#ffffff")
        badge = "🔥" if s["score"] >= 85 else ("⭐" if s["score"] >= 75 else ""  )
        rows_html += f"""
        <tr style="background:{bg}">
          <td style="padding:8px"><strong>{badge} {s['symbol']}</strong></td>
          <td style="padding:8px;text-align:center">{s['score']}</td>
          <td style="padding:8px">{s['setup_type']}</td>
          <td style="padding:8px">₹{s['entry']}</td>
          <td style="padding:8px;color:#c0392b">₹{s['stop_loss']}</td>
          <td style="padding:8px;color:#27ae60">₹{s['target_1']}</td>
          <td style="padding:8px;text-align:center">{s['risk_reward']}x</td>
          <td style="padding:8px">{s['market_regime']}</td>
        </tr>"""

    html = f"""
<div style="font-family:sans-serif;max-width:720px;margin:0 auto;">

  <div style="background:#004a99;color:white;padding:16px 20px;border-radius:8px 8px 0 0;">
    <h2 style="margin:0;font-size:18px;">🛡️ NSE Institutional Swing Setups</h2>
    <p style="margin:6px 0 0;font-size:13px;opacity:0.85;">
      Scan date: <strong>{scan_date}</strong> &nbsp;·&nbsp;
      {len(sorted_setups)} setups &nbsp;·&nbsp;
      {elite_count} elite 🔥 &nbsp;·&nbsp; {strong_count} strong ⭐
    </p>
  </div>

  <div style="background:#fff3cd;border:1px solid #ffc107;padding:10px 16px;
              font-size:12px;color:#856404;line-height:1.5;">
    ⚠️ <strong>These signals are valid for today ({scan_date}) only.</strong>
    A stock's setup changes every day. Always verify the chart before acting.
    This is not investment advice.
  </div>

  <table border="1" style="border-collapse:collapse;width:100%;font-size:13px;margin-top:0;">
    <tr style="background:#004a99;color:white;">
      <th style="padding:8px">Symbol</th>
      <th style="padding:8px">Score</th>
      <th style="padding:8px">Setup</th>
      <th style="padding:8px">Entry</th>
      <th style="padding:8px">Stop Loss</th>
      <th style="padding:8px">T1 (2R)</th>
      <th style="padding:8px">RR</th>
      <th style="padding:8px">Regime</th>
    </tr>
    {rows_html}
  </table>

  <p style="font-size:12px;color:#666;padding:10px 0 0;">
    Open the SwingScanner dashboard for full score breakdown and all 3 targets.
  </p>
</div>
"""
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        logger.info("✅ Email sent to %s.", receiver_email)
    except Exception as exc:
        logger.error("❌ Email failed: %s", exc)


# ---------------------------------------------------------------------------
# Main scan routine
# ---------------------------------------------------------------------------

def run_automation() -> None:
    try:
        # Use IST date — cron runs at 14:00 UTC = 19:30 IST, same calendar day
        from datetime import timedelta
        ist_now = datetime.now(timezone.utc) + timedelta(hours=IST_OFFSET_HRS)
        today   = ist_now.date()

        # ── 0. Guard: skip weekends ───────────────────────────────────────
        if today.weekday() >= 5:
            logger.info("Today is %s IST — NSE closed. Exiting.", today.strftime("%A"))
            return

        logger.info("Starting NSE scan for %s (IST)...", today)

        # ── 1. Init DB ────────────────────────────────────────────────────
        init_db()

        # ── 2. Refresh Bhavcopy cache (non-fatal) ─────────────────────────
        try:
            logger.info("Refreshing Bhavcopy cache...")
            refresh_bhavcopy_cache(days=500)
        except Exception as exc:
            logger.warning("Bhavcopy cache refresh failed (non-fatal): %s", exc)

        # ── 3. Purge today's rows so re-runs are idempotent ───────────────
        logger.info("Purging any existing rows for %s...", today)
        with db_engine.connect() as conn:
            conn.execute(text("DELETE FROM pro_scans_v2 WHERE scan_date = :d"), {"d": today})
            conn.commit()

        # ── 4. Fetch symbols ──────────────────────────────────────────────
        symbols = DataPipeline.get_nse500_symbols()
        symbols = [s.strip() for s in symbols if s and not s.startswith("DUMMY")]
        logger.info("Scanning %d symbols...", len(symbols))

        # ── 5. Fetch index data ───────────────────────────────────────────
        logger.info("Fetching Nifty 50 index...")
        mkt_df = DataPipeline.fetch_market_data("^NSEI")
        if mkt_df is None:
            logger.warning("Nifty index unavailable — using synthetic baseline.")
            mkt_df = _synthetic_index()

        logger.info("Fetching Nifty MidCap 50...")
        mid_df = DataPipeline.fetch_market_data("^NSEMDCP50")
        if mid_df is None:
            logger.warning("MidCap index unavailable — using Nifty as proxy.")
            mid_df = mkt_df

        # ── 6. Batch fetch stock data ─────────────────────────────────────
        logger.info("Starting batch data fetch...")
        all_data = DataPipeline.fetch_batch_data(symbols)

        if all_data is None or all_data.empty:
            raise RuntimeError(
                "All data sources (yfinance, yahooquery, Bhavcopy) exhausted."
            )

        available_tickers = set(all_data.columns.get_level_values(0))
        logger.info("Data available for %d tickers.", len(available_tickers))

        # ── 7. Analysis loop with partial flush ───────────────────────────
        logger.info("Starting analysis...")
        pending_batch: list[dict] = []
        analysed = skipped = total_setups_found = 0

        for sym in symbols:
            ticker_sym = f"{sym}.NS"
            try:
                if ticker_sym not in available_tickers:
                    skipped += 1
                    continue

                df = all_data[ticker_sym].dropna()
                if len(df) < 150:
                    skipped += 1
                    continue

                engine = InstitutionalEngine(df, mkt_df, mid_df)
                score, setup_type, explanation = engine.get_contextual_score()
                analysed += 1

                if score >= SCORE_THRESHOLD:
                    levels = RiskManager.get_levels(df)
                    if levels:
                        pending_batch.append({
                            "symbol":        sym,
                            "scan_date":     today,
                            "score":         int(score),
                            "setup_type":    setup_type,
                            "market_regime": "BULLISH" if score > 75 else "NEUTRAL",
                            "entry":         float(levels["entry"]),
                            "stop_loss":     float(levels["stop_loss"]),
                            "target_1":      float(levels["t1"]),
                            "target_2":      float(levels["t2"]),
                            "target_3":      float(levels["t3"]),
                            "risk_reward":   float(levels["rr"]),
                            "explanation":   str(explanation),
                        })
                        total_setups_found += 1

                        if len(pending_batch) >= FLUSH_EVERY:
                            _flush_batch(pending_batch)

            except Exception:
                logger.debug("Error processing %s:\n%s", sym, traceback.format_exc())
                continue

        logger.info(
            "Analysis complete: %d analysed, %d skipped, %d total setups found.",
            analysed, skipped, total_setups_found,
        )

        # ── 8. Final flush ────────────────────────────────────────────────
        _flush_batch(pending_batch)

        # ── 9. Read back from DB and email — today's rows only ────────────
        with db_engine.connect() as conn:
            rows = list(conn.execute(
                text("SELECT * FROM pro_scans_v2 WHERE scan_date = :d ORDER BY score DESC"),
                {"d": today},
            ).mappings().all())

        logger.info("✅ Scan complete for %s. %d setups saved.", today, len(rows))
        send_email(rows, today)

    except Exception:
        logger.critical("FATAL ERROR:\n%s", traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    run_automation()
