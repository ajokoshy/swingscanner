"""
app.py  —  SwingScanner v2  (Streamlit UI)

Dashboard shows TODAY'S scan results only.
If no scan has run today, it shows a clear waiting state — never silently
displays stale historical data as if it were current signals.

Historical data (last 7 days) is available in a separate collapsed section
so it is clearly labelled as past — not mixed with today's view.
"""

import os
import time
from datetime import datetime, timezone, timedelta

import requests
import streamlit as st
from sqlalchemy import text

from database_manager import init_db, engine as db_engine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCORE_THRESHOLD = 70
IST_OFFSET      = timedelta(hours=5, minutes=30)

# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="🛡️ SwingScanner Pro",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()

# ---------------------------------------------------------------------------
# GitHub credentials — st.secrets first (Streamlit Cloud), then env (local)
# ---------------------------------------------------------------------------

def _secret(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)


GH_TOKEN    = _secret("GH_TOKEN")
GH_OWNER    = _secret("GH_OWNER")
GH_REPO     = _secret("GH_REPO", "swingscanner")
WORKFLOW_ID = "daily_scan.yml"


def _gh_headers() -> dict:
    return {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def trigger_gh_scan() -> tuple[bool, str]:
    if not (GH_TOKEN and GH_OWNER and GH_REPO):
        return False, (
            "GitHub credentials not configured. "
            "Add GH_TOKEN, GH_OWNER, GH_REPO to Streamlit secrets."
        )
    url = (
        f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}"
        f"/actions/workflows/{WORKFLOW_ID}/dispatches"
    )
    try:
        resp = requests.post(
            url, headers=_gh_headers(), json={"ref": "main"}, timeout=15
        )
        if resp.status_code == 204:
            return True, "✅ Scan triggered! Results will appear here in ~10 minutes."
        return False, f"GitHub API error {resp.status_code}: {resp.text[:200]}"
    except Exception as exc:
        return False, f"Request failed: {exc}"


def get_last_run_status() -> dict | None:
    if not (GH_TOKEN and GH_OWNER and GH_REPO):
        return None
    url = (
        f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}"
        f"/actions/workflows/{WORKFLOW_ID}/runs?per_page=1"
    )
    try:
        resp = requests.get(url, headers=_gh_headers(), timeout=10)
        runs = resp.json().get("workflow_runs", [])
        return runs[0] if runs else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Time helper
# ---------------------------------------------------------------------------

def _to_ist(utc_str: str) -> str:
    """Convert a GitHub API UTC timestamp (2026-06-15T14:15:00Z) to IST string."""
    try:
        dt_utc = datetime.strptime(utc_str[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        dt_ist = dt_utc + IST_OFFSET
        return dt_ist.strftime("%-d %b %Y, %I:%M %p IST")
    except Exception:
        return utc_str[:16].replace("T", " ") + " UTC"


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("Scanner Controls")
st.sidebar.markdown("---")

if st.sidebar.button("🚀 Trigger Full NSE500 Scan", use_container_width=True):
    ok, msg = trigger_gh_scan()
    if ok:
        st.sidebar.success(msg)
    else:
        st.sidebar.error(msg)
        st.sidebar.caption(
            "You can also trigger manually: GitHub → your repo → "
            "Actions → Daily NSE Market Scan → Run workflow."
        )

st.sidebar.markdown("---")

with st.sidebar.expander("📊 Last Scan Status", expanded=True):
    run = get_last_run_status()
    if run:
        status     = run.get("status", "unknown")
        conclusion = run.get("conclusion") or "—"
        started    = run.get("created_at", "")
        finished   = run.get("updated_at", "")
        icon = {"completed": "✅" if conclusion == "success" else "❌",
                "in_progress": "⏳", "queued": "🕐"}.get(status, "❓")
        st.write(f"**Status:** {icon} {status} / {conclusion}")
        if started:
            st.write(f"**Started:** {_to_ist(started)}")
        if finished and status == "completed":
            st.write(f"**Finished:** {_to_ist(finished)}")
        if GH_OWNER and GH_REPO:
            st.markdown(
                f"[View on GitHub](https://github.com/{GH_OWNER}/{GH_REPO}/actions)"
            )
    else:
        st.write("No run data (GH_TOKEN not set, or no runs yet).")

st.sidebar.markdown("---")
st.sidebar.info(
    "**How it works**\n\n"
    "1. Click Trigger Scan → GitHub Actions starts\n"
    "2. 500 NSE stocks fetched + scored\n"
    "3. Setups ≥ 70 saved to database\n"
    "4. Email report sent to you\n"
    "5. This dashboard shows **today's results only**\n\n"
    "Scan runs daily at 8:04 PM IST automatically."
)

st.sidebar.markdown("---")

with st.sidebar.expander("🗑️ Clean Up Old Data"):
    now_ist_cleanup = datetime.now(timezone.utc) + IST_OFFSET
    today_cleanup   = now_ist_cleanup.date()

    with db_engine.connect() as conn:
        old_count = conn.execute(
            text("SELECT COUNT(*) AS c FROM pro_scans_v2 WHERE scan_date < :d"),
            {"d": today_cleanup},
        ).mappings().first()["c"]

    if old_count == 0:
        st.caption("No rows older than today. Nothing to clean up.")
    else:
        st.write(f"**{old_count}** rows from before today ({today_cleanup}) exist.")
        st.caption("This permanently deletes them. Today's data is never touched.")

        confirm = st.checkbox(f"Yes, delete all {old_count} old rows", key="confirm_cleanup")

        if st.button("🗑️ Delete Old Entries", disabled=not confirm, use_container_width=True):
            with db_engine.connect() as conn:
                result = conn.execute(
                    text("DELETE FROM pro_scans_v2 WHERE scan_date < :d"),
                    {"d": today_cleanup},
                )
                conn.commit()
                deleted = result.rowcount
            st.success(f"✅ Deleted {deleted} rows older than {today_cleanup}.")
            st.session_state["confirm_cleanup"] = False
            time.sleep(1.5)
            st.rerun()

# ---------------------------------------------------------------------------
# Main dashboard
# ---------------------------------------------------------------------------

st.title("🛡️ Institutional NSE Swing Platform")
st.markdown(
    "**Real-time swing setup detection** — "
    "multi-timeframe trend · momentum · volume · breakout"
)

col_r1, col_r2 = st.columns([3, 1])
with col_r2:
    auto_refresh = st.toggle("Auto-refresh (30s)", value=False)

# ---------------------------------------------------------------------------
# Load results — TODAY ONLY
# ---------------------------------------------------------------------------

try:
    now_ist = datetime.now(timezone.utc) + IST_OFFSET
    today   = now_ist.date()

    with db_engine.connect() as conn:

        # ── Today's results ───────────────────────────────────────────────
        today_rows = list(conn.execute(
            text("SELECT * FROM pro_scans_v2 WHERE scan_date = :d ORDER BY score DESC"),
            {"d": today},
        ).mappings().all())

        # ── Last scan date (for history section) ──────────────────────────
        last_date_row = conn.execute(
            text("SELECT MAX(scan_date) AS last_date FROM pro_scans_v2")
        ).mappings().first()
        last_scan_date = last_date_row["last_date"] if last_date_row else None

    # ── TODAY: data exists ────────────────────────────────────────────────
    if today_rows:
        rows = today_rows

        elite  = [r for r in rows if r["score"] >= 85]
        strong = [r for r in rows if 75 <= r["score"] < 85]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Today's Setups", len(rows))
        m2.metric("🔥 Elite (85+)", len(elite))
        m3.metric("⭐ Strong (75–84)", len(strong))
        m4.metric("Avg Score", f"{sum(r['score'] for r in rows) / len(rows):.1f}")

        st.success(f"✅ Scan completed for **{today}** — {len(rows)} active setups found")

        # Filters
        fc1, fc2 = st.columns(2)
        with fc1:
            setup_types   = sorted({r["setup_type"] for r in rows})
            selected_type = st.selectbox("Filter by setup", ["All"] + setup_types)
        with fc2:
            regime_types    = sorted({r["market_regime"] for r in rows})
            selected_regime = st.selectbox("Filter by regime", ["All"] + regime_types)

        filtered = [
            r for r in rows
            if (selected_type   == "All" or r["setup_type"]    == selected_type)
            and (selected_regime == "All" or r["market_regime"] == selected_regime)
        ]

        st.markdown(f"### 🎯 Today's setups ({len(filtered)} shown)")

        for res in filtered:
            badge  = "🔥 ELITE" if res["score"] >= 85 else ("⭐ STRONG" if res["score"] >= 75 else "✅")
            header = (
                f"{badge}  **{res['symbol']}**  |  "
                f"Score: **{res['score']}/100**  |  {res['setup_type']}  |  "
                f"{res['market_regime']}"
            )
            with st.expander(header):
                c1, c2, c3 = st.columns([1, 1, 1.5])
                with c1:
                    st.markdown("**📍 Trade Levels**")
                    st.code(
                        f"Entry:       ₹{res['entry']}\n"
                        f"Stop Loss:   ₹{res['stop_loss']}\n"
                        f"Risk/Reward: {res['risk_reward']}x"
                    )
                with c2:
                    st.markdown("**🎯 Targets**")
                    st.success(f"T1 (2R): ₹{res['target_1']}")
                    st.success(f"T2 (3R): ₹{res['target_2']}")
                    st.success(f"T3 (5R): ₹{res['target_3']}")
                with c3:
                    st.markdown("**📊 Score Breakdown**")
                    for p in str(res["explanation"]).split(" | "):
                        st.write(f"• {p}")
                    st.caption(f"Scanned: {res['scan_date']}  |  Regime: {res['market_regime']}")

    # ── TODAY: no scan yet ────────────────────────────────────────────────
    else:
        st.warning(
            f"⏳ **No scan has run today ({today} IST) yet.**\n\n"
            "Setups from previous scans are **not shown** here to avoid acting on stale signals. "
            "A stock that was bullish yesterday may have broken down today.\n\n"
            "The daily scan runs automatically at **8:04 PM IST**. "
            "To scan right now, click **'Trigger Full NSE500 Scan'** in the sidebar."
        )

        # Show last scan date as context (but not the data)
        if last_scan_date:
            days_ago = (today - last_scan_date).days
            st.caption(
                f"Last scan was on **{last_scan_date}** "
                f"({'yesterday' if days_ago == 1 else f'{days_ago} days ago'}). "
                f"Use the History section below to view it."
            )

    # ── HISTORY: clearly labelled, collapsed by default ───────────────────
    st.markdown("---")
    with st.expander(
        "📁 Historical scans — last 7 days  "
        "*(these are past signals, not current — verify before trading)*",
        expanded=False,
    ):
        with db_engine.connect() as conn:
            hist_rows = list(conn.execute(
                text("""
                    SELECT * FROM pro_scans_v2
                    WHERE scan_date >= :cutoff
                      AND scan_date < :today
                    ORDER BY scan_date DESC, score DESC
                    LIMIT 200
                """),
                {"cutoff": today - timedelta(days=7), "today": today},
            ).mappings().all())

        if not hist_rows:
            st.info("No historical scans in the last 7 days.")
        else:
            # Group by date
            dates_seen: list = []
            by_date: dict    = {}
            for r in hist_rows:
                d = str(r["scan_date"])
                if d not in by_date:
                    by_date[d] = []
                    dates_seen.append(d)
                by_date[d].append(r)

            st.warning(
                "⚠️ These are **past** scan results. Market conditions change daily. "
                "Do not use these as current buy/sell signals without re-verifying the chart."
            )

            selected_date = st.selectbox(
                "View scan date",
                options=dates_seen,
                format_func=lambda d: f"{d}  ({len(by_date[d])} setups)",
            )

            for res in by_date[selected_date]:
                badge  = "🔥" if res["score"] >= 85 else ("⭐" if res["score"] >= 75 else "•")
                header = (
                    f"{badge} **{res['symbol']}** — "
                    f"{res['score']}/100 · {res['setup_type']}"
                )
                with st.expander(header):
                    c1, c2 = st.columns(2)
                    with c1:
                        st.code(
                            f"Entry:       ₹{res['entry']}\n"
                            f"Stop Loss:   ₹{res['stop_loss']}\n"
                            f"Risk/Reward: {res['risk_reward']}x"
                        )
                    with c2:
                        st.write(f"T1: ₹{res['target_1']}  |  T2: ₹{res['target_2']}  |  T3: ₹{res['target_3']}")
                        for p in str(res["explanation"]).split(" | "):
                            st.caption(f"• {p}")

except Exception as exc:
    st.error(f"Dashboard error: {exc}")

# ---------------------------------------------------------------------------
# Auto-refresh
# ---------------------------------------------------------------------------

if auto_refresh:
    time.sleep(30)
    st.rerun()

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("---")
st.caption(
    f"SwingScanner v2  |  NSE data via Yahoo Finance (multi-source fallback)  |  "
    f"Score threshold: {SCORE_THRESHOLD}/100  |  "
    f"For educational purposes only — not investment advice."
)
