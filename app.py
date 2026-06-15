"""
app.py  —  SwingScanner v2  (Streamlit UI)

The "Run Scan" button triggers GitHub Actions workflow_dispatch instead of
running the scan inline (which times out on Streamlit Cloud at ~60 s).
Results are read from the Neon database and displayed in real time.
"""

import os
import time
from datetime import datetime, timezone

import requests
import streamlit as st
from sqlalchemy import text

from database_manager import init_db, engine as db_engine

# ---------------------------------------------------------------------------
# Constants (defined at top so they're available everywhere)
# ---------------------------------------------------------------------------

SCORE_THRESHOLD = 70

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
# GitHub credentials
# Read from st.secrets first (Streamlit Cloud), fall back to env vars (local dev).
# ---------------------------------------------------------------------------

def _secret(key: str, default: str = "") -> str:
    """Read from st.secrets if available, then os.environ."""
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)


GH_TOKEN    = _secret("GH_TOKEN")
GH_OWNER    = _secret("GH_OWNER")
GH_REPO     = _secret("GH_REPO", "swingscanner")
WORKFLOW_ID = "daily_scan.yml"


def _gh_headers() -> dict:
    """Build GitHub API headers fresh each call (token may be updated)."""
    return {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


# ---------------------------------------------------------------------------
# GitHub Actions helpers
# ---------------------------------------------------------------------------

def trigger_gh_scan() -> tuple[bool, str]:
    """Trigger daily_scan.yml via workflow_dispatch API."""
    if not (GH_TOKEN and GH_OWNER and GH_REPO):
        return False, (
            "GitHub credentials not configured. "
            "Add GH_TOKEN, GH_OWNER, and GH_REPO to your Streamlit secrets "
            "(or .env for local dev). See UPGRADE.md for instructions."
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
    """Return the most recent workflow run dict, or None."""
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
            st.write(f"**Started:** {started[:16].replace('T', ' ')} UTC")
        if finished and status == "completed":
            st.write(f"**Finished:** {finished[:16].replace('T', ' ')} UTC")
        if GH_OWNER and GH_REPO:
            st.markdown(
                f"[View run on GitHub](https://github.com/{GH_OWNER}/{GH_REPO}/actions)"
            )
    else:
        st.write("No run data (GH_TOKEN not set, or no runs yet).")

st.sidebar.markdown("---")
st.sidebar.info(
    "**How it works**\n\n"
    "1. Click Trigger Scan → GitHub Actions starts\n"
    "2. 500 NSE stocks fetched + scored\n"
    "3. Setups ≥70 saved to database\n"
    "4. Email report sent to you\n"
    "5. This dashboard shows results\n\n"
    "The scan runs in GitHub infra — no Streamlit timeout."
)

# ---------------------------------------------------------------------------
# Main dashboard
# ---------------------------------------------------------------------------

st.title("🛡️ Institutional NSE Swing Platform")
st.markdown(
    "**Real-time swing setup detection** — "
    "multi-timeframe trend · momentum · volume · breakout"
)

# Auto-refresh toggle — defined before the try block so it's always available
col_r1, col_r2 = st.columns([3, 1])
with col_r2:
    auto_refresh = st.toggle("Auto-refresh (30s)", value=False)

# ---------------------------------------------------------------------------
# Load results from DB
# ---------------------------------------------------------------------------

try:
    today = datetime.now(timezone.utc).date()

    with db_engine.connect() as conn:
        today_rows = conn.execute(
            text("SELECT * FROM pro_scans_v2 WHERE scan_date = :d ORDER BY score DESC"),
            {"d": today},
        ).mappings().all()

        if today_rows:
            rows       = list(today_rows)
            scan_label = f"Today's setups — {today}"
        else:
            rows = list(conn.execute(
                text(
                    "SELECT * FROM pro_scans_v2 "
                    "ORDER BY scan_date DESC, score DESC LIMIT 50"
                )
            ).mappings().all())
            scan_label = "Latest historical setups (no scan run today yet)"

    if rows:
        elite  = [r for r in rows if r["score"] >= 85]
        strong = [r for r in rows if 75 <= r["score"] < 85]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Setups", len(rows))
        m2.metric("🔥 Elite (85+)", len(elite))
        m3.metric("⭐ Strong (75–84)", len(strong))
        m4.metric("Avg Score", f"{sum(r['score'] for r in rows) / len(rows):.1f}")

        st.markdown(f"### 🎯 {scan_label} ({len(rows)} setups)")

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

        # Result cards
        for res in filtered:
            is_elite = res["score"] >= 85
            badge    = "🔥 ELITE" if is_elite else ("⭐ STRONG" if res["score"] >= 75 else "✅")
            header   = (
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
                    st.caption(
                        f"Scan: {res['scan_date']}  |  Regime: {res['market_regime']}"
                    )
    else:
        st.warning(
            "No setups in the database yet. "
            "Click **'Trigger Full NSE500 Scan'** in the sidebar to run the first scan."
        )

except Exception as exc:
    st.error(f"Dashboard error: {exc}")

# ---------------------------------------------------------------------------
# Auto-refresh (auto_refresh is always defined above the try block)
# ---------------------------------------------------------------------------

if auto_refresh:
    time.sleep(30)
    st.rerun()

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("---")
st.caption(
    f"SwingScanner v2  |  Data: NSE + Yahoo Finance (multi-source fallback)  |  "
    f"Setups shown: score ≥ {SCORE_THRESHOLD}/100  |  "
    f"For educational purposes only — not investment advice."
)
