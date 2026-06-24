"""
scanner_cron.py  —  SwingScanner v2
Automated daily scan runner (GitHub Actions / any cron).
"""

import logging
import os
import smtplib
import sys
import traceback
from datetime import datetime, timezone, timedelta, date as date_type
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd
from sqlalchemy import text

from data_fetcher import DataPipeline, refresh_bhavcopy_cache
from database_manager import init_db, run_migrations, engine as db_engine
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
         entry, stop_loss, target_1, target_2, target_3, risk_reward,
         explanation, entry_score, entry_label)
    VALUES
        (:symbol, :scan_date, :score, :setup_type, :market_regime,
         :entry, :stop_loss, :target_1, :target_2, :target_3, :risk_reward,
         :explanation, :entry_score, :entry_label)
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

    by_score     = sorted(setups, key=lambda x: x["score"], reverse=True)
    entry_ready  = [s for s in by_score if (s.get("entry_score") or 0) == 5]
    almost_ready = [s for s in by_score if (s.get("entry_score") or 0) == 4]
    elite_count  = sum(1 for s in by_score if s["score"] >= 85)
    strong_count = sum(1 for s in by_score if 75 <= s["score"] < 85)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"NSE Swings {scan_date} — {len(entry_ready)} entry-ready · {len(by_score)} total"
    msg["From"]    = f"NSE Pro Scanner <{sender_email}>"
    msg["To"]      = receiver_email

    # ── shared styles ──────────────────────────────────────────────────────
    TH  = "padding:8px 10px;text-align:left;font-weight:600;white-space:nowrap;"
    TH_C = "padding:8px 10px;text-align:center;font-weight:600;white-space:nowrap;"
    TD  = "padding:7px 10px;border-top:1px solid #e0e0e0;"
    TD_C = "padding:7px 10px;border-top:1px solid #e0e0e0;text-align:center;"
    TD_R = "padding:7px 10px;border-top:1px solid #e0e0e0;color:#c0392b;"
    TD_G = "padding:7px 10px;border-top:1px solid #e0e0e0;color:#27ae60;"

    def _er_rows(rows):
        out = []
        for s in rows:
            bg = "#f0faf0" if rows.index(s) % 2 == 0 else "#e8f5e8"
            out.append(
                f'<tr style="background:{bg}">'
                f'<td style="{TD}"><strong>{s["symbol"]}</strong></td>'
                f'<td style="{TD_C}">{s["score"]}</td>'
                f'<td style="{TD}">{s["setup_type"]}</td>'
                f'<td style="{TD}">₹{s["entry"]}</td>'
                f'<td style="{TD_R}">₹{s["stop_loss"]}</td>'
                f'<td style="{TD_G}">₹{s["target_1"]}</td>'
                f'<td style="{TD_G}">₹{s["target_2"]}</td>'
                f'<td style="{TD_C}">{s["risk_reward"]}x</td>'
                f'</tr>'
            )
        return "".join(out)

    def _ar_rows(rows):
        out = []
        for s in rows:
            bg = "#fffdf0" if rows.index(s) % 2 == 0 else "#fff8dc"
            out.append(
                f'<tr style="background:{bg}">'
                f'<td style="{TD}">{s["symbol"]}</td>'
                f'<td style="{TD_C}">{s["score"]}</td>'
                f'<td style="{TD}">{s["setup_type"]}</td>'
                f'<td style="{TD}">₹{s["entry"]}</td>'
                f'<td style="{TD_R}">₹{s["stop_loss"]}</td>'
                f'<td style="{TD_G}">₹{s["target_1"]}</td>'
                f'<td style="{TD_C}">{s["risk_reward"]}x</td>'
                f'</tr>'
            )
        return "".join(out)

    def _all_rows(rows):
        out = []
        for i, s in enumerate(rows):
            escore = s.get("entry_score") or 0
            bg     = "#f0faf0" if escore == 5 else ("#fffdf0" if escore == 4 else ("#ffffff" if i % 2 == 0 else "#f9f9f9"))
            badge  = "🔥 " if s["score"] >= 85 else ("⭐ " if s["score"] >= 75 else "")
            eq     = "✅" if escore == 5 else (f"⚠️ {escore}/5" if escore >= 4 else f"{escore}/5")
            out.append(
                f'<tr style="background:{bg}">'
                f'<td style="{TD}">{badge}{s["symbol"]}</td>'
                f'<td style="{TD_C}">{s["score"]}</td>'
                f'<td style="{TD}">{s["setup_type"]}</td>'
                f'<td style="{TD_C}">{eq}</td>'
                f'<td style="{TD}">₹{s["entry"]}</td>'
                f'<td style="{TD_R}">₹{s["stop_loss"]}</td>'
                f'<td style="{TD_G}">₹{s["target_1"]}</td>'
                f'<td style="{TD_C}">{s["risk_reward"]}x</td>'
                f'</tr>'
            )
        return "".join(out)

    # ── entry-ready section ────────────────────────────────────────────────
    er_section = ""
    if entry_ready:
        er_section = (
            '<div style="margin:16px 0;padding:14px;background:#e8f5e8;border-left:4px solid #28a745;border-radius:4px;">' +
            f'<p style="margin:0 0 10px;font-size:15px;font-weight:600;color:#155724;">✅ Entry-Ready Now — {len(entry_ready)} stock{"s" if len(entry_ready)>1 else ""} (Buy Tomorrow)</p>' +
            '<p style="margin:0 0 12px;font-size:12px;color:#155724;">All 5 conditions passed: not extended · RSI in buy zone · volatility contracting · near support · R/R ≥ 2</p>' +
            '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:13px;">' +
            f'<tr style="background:#28a745;color:#ffffff;"><th style="{TH}">Symbol</th><th style="{TH_C}">Score</th><th style="{TH}">Setup</th><th style="{TH}">Entry</th><th style="{TH}">Stop Loss</th><th style="{TH}">T1</th><th style="{TH}">T2</th><th style="{TH_C}">RR</th></tr>' +
            _er_rows(entry_ready) +
            '</table></div>'
        )

    # ── almost-ready section ───────────────────────────────────────────────
    ar_section = ""
    if almost_ready:
        ar_section = (
            '<div style="margin:16px 0;padding:14px;background:#fff8dc;border-left:4px solid #ffc107;border-radius:4px;">' +
            f'<p style="margin:0 0 10px;font-size:15px;font-weight:600;color:#856404;">⚠️ Almost Ready — {len(almost_ready)} stock{"s" if len(almost_ready)>1 else ""} (4/5 conditions)</p>' +
            '<p style="margin:0 0 12px;font-size:12px;color:#856404;">One condition failing. Could flip to entry-ready tomorrow — keep on watchlist.</p>' +
            '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:13px;">' +
            f'<tr style="background:#e6a817;color:#ffffff;"><th style="{TH}">Symbol</th><th style="{TH_C}">Score</th><th style="{TH}">Setup</th><th style="{TH}">Entry</th><th style="{TH}">Stop Loss</th><th style="{TH}">T1</th><th style="{TH_C}">RR</th></tr>' +
            _ar_rows(almost_ready) +
            '</table></div>'
        )

    # ── full table ─────────────────────────────────────────────────────────
    all_section = (
        '<p style="margin:20px 0 8px;font-size:14px;font-weight:600;color:#333;">📋 All Setups Today</p>' +
        '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:12px;">' +
        f'<tr style="background:#004a99;color:#ffffff;"><th style="{TH}">Symbol</th><th style="{TH_C}">Score</th><th style="{TH}">Setup</th><th style="{TH_C}">Entry Quality</th><th style="{TH}">Entry</th><th style="{TH}">Stop Loss</th><th style="{TH}">T1</th><th style="{TH_C}">RR</th></tr>' +
        _all_rows(by_score) +
        '</table>'
    )

    html = (
        '<div style="font-family:Arial,sans-serif;max-width:700px;margin:0 auto;color:#222;">' +
        # header
        f'<div style="background:#004a99;color:#ffffff;padding:18px 20px;border-radius:6px 6px 0 0;">' +
        f'<h2 style="margin:0 0 6px;font-size:20px;">🛡️ NSE Institutional Swing Setups</h2>' +
        f'<p style="margin:0;font-size:13px;opacity:0.9;">{scan_date} &nbsp;·&nbsp; {len(by_score)} total &nbsp;·&nbsp; ' +
        f'<strong>{len(entry_ready)} entry-ready ✅</strong> &nbsp;·&nbsp; {len(almost_ready)} almost-ready ⚠️ ' +
        f'&nbsp;·&nbsp; {elite_count} elite 🔥 &nbsp;·&nbsp; {strong_count} strong ⭐</p></div>' +
        # disclaimer
        f'<div style="background:#fff3cd;border-left:4px solid #ffc107;padding:10px 14px;font-size:12px;color:#856404;">' +
        f'⚠️ <strong>Signals valid for {scan_date} only.</strong> Market conditions change daily. ' +
        f'Always verify the chart before acting. Not investment advice.</div>' +
        # body
        f'<div style="padding:0 4px;">{er_section}{ar_section}{all_section}</div>' +
        # footer
        '<p style="font-size:11px;color:#999;padding:14px 4px 4px;">Open SwingScanner dashboard for full score breakdown and all 3 targets.</p>' +
        '</div>'
    )

    msg.attach(MIMEText(html, "html", "utf-8"))

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
        # Use IST date — cron runs at 14:34 UTC = 20:04 IST, same calendar day
        ist_now = datetime.now(timezone.utc) + timedelta(hours=IST_OFFSET_HRS)
        today   = ist_now.date()

        # ── 0. Guard: skip weekends ───────────────────────────────────────
        if today.weekday() >= 5:
            logger.info("Today is %s IST — NSE closed. Exiting.", today.strftime("%A"))
            return

        logger.info("Starting NSE scan for %s (IST)...", today)

        # ── 1. Init DB + run migrations ──────────────────────────────────
        init_db()
        run_migrations()

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
                        eq     = engine.get_entry_quality()
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
                            "entry_score":   int(eq["entry_score"]),
                            "entry_label":   str(eq["entry_label"]),
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
