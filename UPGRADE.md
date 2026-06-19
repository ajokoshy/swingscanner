# SwingScanner v2 — Complete Upgrade Guide

## What was fixed and why

| # | Severity | File | Problem in v1 | Fix in v2 |
|---|---|---|---|---|
| 1 | 🔴 Critical | `app.py` | `SyntaxError` — walrus operator `:=` misused in list comprehension. App would not start. | Removed walrus operator; `SCORE_THRESHOLD = 70` defined once at top of file. |
| 2 | 🔴 Critical | `app.py` | `NameError` — `auto_refresh` defined inside `try` block, used after it. Any DB error would crash the whole page. | Moved `auto_refresh` definition before the `try` block. |
| 3 | 🔴 Critical | `app.py` | `GH_TOKEN` read via `os.getenv()` only. On Streamlit Cloud, secrets live in `st.secrets`, not env vars — trigger button always failed silently. | Added `_secret()` helper that reads `st.secrets` first, then falls back to `os.getenv()`. Works on both Streamlit Cloud and local dev. |
| 4 | 🔴 Critical | `data_fetcher.py` | `yf.download()` with exactly 1 symbol returns a flat DataFrame (no MultiIndex). The last chunk of an odd-numbered symbol list would corrupt the entire batch concat. | Single-symbol chunks are now wrapped with `pd.concat({sym: df})` to force consistent MultiIndex. |
| 5 | 🟡 High | `scanner_cron.py` | Log message "setups found" showed only the unflushed remainder, not total found. Hard to know if scan was working. | Added `total_setups_found` counter tracked separately from `pending_batch`. |
| 6 | 🟡 High | `scanner_cron.py` | `_synthetic_index()` used `pd.date_range(freq='B')` which produces one fewer row when today is a weekend. Engine received mismatched arrays. | Replaced with `pd.bdate_range(start='2010-01-01', end=now)[-300:]` which always yields exactly 300 rows. |
| 7 | 🟡 High | `data_fetcher.py` | Bhavcopy cache used `.parquet` only — crashes if `pyarrow` is not installed. | Added `_has_parquet()` check; falls back to `.csv` if pyarrow is absent. Uses `_cache_read()` / `_cache_write()` helpers throughout. |
| 8 | 🟠 Medium | `data_fetcher.py` | `yahooquery` Adjclose→Close rename was dead code. yahooquery default columns are lowercase; `.capitalize()` already maps `close`→`Close`. | Removed dead rename; added comment explaining the mapping. |
| 9 | 🟠 Medium | `scanner_cron.py` | `timedelta` imported but never used. | Removed. |
| 10 | 🟠 Medium | `app.py` | `timedelta` imported but never used. | Removed. |
| 11 | 🟠 Medium | `engine_pro.py` | `numpy` imported as `np` but never used. | Removed. |
| 12 | 🟢 Low | `app.py` | `SCORE_THRESHOLD` was re-defined at the bottom of the file as dead code. | Removed the duplicate definition. |

---

## Files to replace

Replace these files in your repository root:

```
app.py                            ← rewritten (4 critical fixes)
data_fetcher.py                   ← rewritten (3-source chain, single-symbol fix, CSV fallback)
scanner_cron.py                   ← rewritten (partial flush, synthetic index fix, better logging)
database_manager.py               ← updated (pool_recycle, cleaner logging)
engine_pro.py                     ← cleaned (unused import removed)
requirements.txt                  ← updated (pyarrow, yahooquery pinned)
runtime.txt                       ← unchanged
.github/workflows/daily_scan.yml  ← updated (new cron time, pip cache, timeout)
```

Do **not** replace (unchanged):
```
trading_manager.py
backtest_engine.py
```

---

## Step 1 — Update your repository

### Option A: GitHub web UI (easiest, no git needed)

1. Go to your repo on GitHub
2. For each file listed above, click the file → pencil icon (Edit) → paste the new content → **Commit changes**
3. Repeat for all 8 files

### Option B: Git (faster if you have it set up locally)

```bash
# In your local repo folder
cd your-swingscanner-folder

# Copy the new files from the extracted zip
cp path/to/swingscanner-v2/app.py .
cp path/to/swingscanner-v2/data_fetcher.py .
cp path/to/swingscanner-v2/scanner_cron.py .
cp path/to/swingscanner-v2/database_manager.py .
cp path/to/swingscanner-v2/engine_pro.py .
cp path/to/swingscanner-v2/requirements.txt .
cp path/to/swingscanner-v2/runtime.txt .
cp path/to/swingscanner-v2/.github/workflows/daily_scan.yml .github/workflows/

git add -A
git commit -m "feat: SwingScanner v2 — multi-source data, bug fixes, GH Actions trigger"
git push
```

---

## Step 2 — Add 3 new GitHub repository secrets

The Streamlit "Trigger Scan" button now calls the GitHub API to fire `workflow_dispatch`.
It needs a token with permission to do that.

### Create the Personal Access Token

1. Go to [github.com](https://github.com) → click your **profile picture** (top right) → **Settings**
2. Scroll to the bottom of the left sidebar → **Developer settings**
3. **Personal access tokens** → **Fine-grained tokens** → **Generate new token**
4. Fill in:
   - **Token name:** `SwingScanner Trigger`
   - **Expiration:** 1 year (or No expiration)
   - **Repository access:** Only select repositories → choose your swingscanner repo
   - **Repository permissions:**
     - `Actions` → **Read and Write**
     - `Contents` → **Read-only**
5. Click **Generate token** → copy the token immediately (you won't see it again)

### Add the secrets to your repo

1. In your repo → **Settings** tab (top nav) → **Secrets and variables** (left sidebar) → **Actions**
2. Click **New repository secret** for each:

| Secret name | Value |
|---|---|
| `GH_TOKEN` | The token you just copied (starts with `ghp_` or `github_pat_`) |
| `GH_OWNER` | Your GitHub username exactly as it appears in your profile URL |
| `GH_REPO` | Your repository name (e.g. `swingscanner` or `swingscanner-main`) |

> **Note:** `DATABASE_URL`, `EMAIL_USER`, `EMAIL_PASS`, `RECEIVER_EMAIL` are unchanged — you don't need to touch them.

---

## Step 3 — Add secrets to Streamlit Cloud

The Streamlit app also needs these values to call the GitHub API when you click the button.

1. Go to [share.streamlit.io](https://share.streamlit.io) → your app → **⋮ menu** → **Settings** → **Secrets**
2. Add/update to look like this (keep your existing DATABASE_URL etc.):

```toml
# Existing secrets — keep as-is
DATABASE_URL    = "postgresql://..."
EMAIL_USER      = "youremail@gmail.com"
EMAIL_PASS      = "your_app_password"
RECEIVER_EMAIL  = "youremail@gmail.com"

# New secrets for v2 Trigger button
GH_TOKEN        = "github_pat_xxxxxxxxxxxx"
GH_OWNER        = "your_github_username"
GH_REPO         = "swingscanner"
```

3. Click **Save** — Streamlit will reboot the app automatically.

---

## Step 4 — Verify the deployment

### Check the Streamlit app loaded correctly

Open your Streamlit app URL. You should see:
- ✅ The dashboard loads without a Python error on screen
- ✅ Sidebar shows "Trigger Full NSE500 Scan" button
- ✅ "Last Scan Status" expander shows run data (or "no runs yet")
- ✅ No red error banner at the top

If you see a red error, click **"See exception"** and check:
- `NameError: SCORE_THRESHOLD` → you still have an old `app.py`
- `OperationalError` on DB → `DATABASE_URL` secret is wrong or Neon is paused

### Test the Trigger button

1. Click **"🚀 Trigger Full NSE500 Scan"** in the sidebar
2. You should see a **green** "Scan triggered!" message
3. Go to your GitHub repo → **Actions** tab
4. You should see a new run called "Daily NSE Market Scan" with status **In progress**

If you see a red error from the button:
- `GitHub API error 401` → `GH_TOKEN` is wrong or expired
- `GitHub API error 404` → `GH_OWNER` or `GH_REPO` is wrong (check exact case)
- `GitHub credentials not configured` → secrets not saved in Streamlit

### Watch the scan run

In the GitHub Actions run:

```
✅ Refreshing Bhavcopy cache: N missing days...     ← building fallback cache
✅ Fetching Nifty 50 index...
✅ Starting batch data fetch...
✅ Batch fetch: trying yfinance+cffi (500 symbols)...
✅ yfinance batch: 94% symbol coverage.              ← or whichever source wins
✅ Analysis complete: 487 analysed, 13 skipped, 42 total setups found.
✅ Flushed 25 setups to DB.
✅ Flushed 17 setups to DB.
✅ Email report sent to youremail@gmail.com.
```

If you see `yahooquery batch: 78% symbol coverage` instead of yfinance — that's the fallback working correctly. Results will still be complete.

If you see `All data sources exhausted` — this means all three sources failed. This is very rare. Wait 30 minutes and re-trigger manually.

---

## Step 5 — Optional: Persist Bhavcopy cache across scans

By default the cache is in `/tmp/bhavcopy_cache/` on the GitHub runner, which resets between runs. This means the first chunk of every scan re-downloads recent days (fast — only 1–2 files). If you want a warm cache that survives runs:

Add this step to `.github/workflows/daily_scan.yml` after the pip cache step:

```yaml
      - name: Restore Bhavcopy cache
        uses: actions/cache@v4
        with:
          path: /tmp/bhavcopy_cache
          key: bhavcopy-${{ runner.os }}-${{ steps.date.outputs.date }}
          restore-keys: |
            bhavcopy-${{ runner.os }}-
```

This is optional — the scan works fine without it.

---

## How the 3-source data fallback works

```
All 500 symbols requested
         │
         ▼
 ┌─────────────────────────────┐
 │  Source 1: yfinance + cffi  │  ← TLS fingerprint spoofing (looks like Chrome)
 │  chunks of 5, 60s timeout   │
 │  3 retries per chunk        │
 └─────────────┬───────────────┘
               │ coverage ≥ 50%?
          YES ─┘  NO ──────────────────────────────────────┐
          use it                                            ▼
                                            ┌──────────────────────────┐
                                            │  Source 2: yahooquery    │
                                            │  different Yahoo endpoint │
                                            │  async batch call         │
                                            └──────────────┬───────────┘
                                                           │ coverage ≥ 30%?
                                                      YES ─┘  NO ────────────┐
                                                      use it                  ▼
                                                              ┌───────────────────────────┐
                                                              │  Source 3: NSE Bhavcopy  │
                                                              │  Daily CSV from NSE site  │
                                                              │  Cached as parquet/csv    │
                                                              │  No Yahoo dependency      │
                                                              └───────────────────────────┘
```

The Bhavcopy cache back-fills 500 trading days (~2 years) automatically on every scan.
After a few days of running, you'll have a complete offline history as insurance.

---

## Frequently asked questions

**Q: Do I need to change my Neon database?**

No. The `pro_scans_v2` table schema is identical. The new `sector_strength` column is `NULL`-able and already handled. No migrations needed.

**Q: The cron changed from 5:00 PM to 8:04 PM IST — why?**

Yahoo Finance sometimes takes 1–2 hours to finalize NSE EOD data after market close (3:30 PM IST). Running at 5:00 PM occasionally fetched incomplete or stale data. 8:04 PM gives Yahoo ~4.5 hours to settle.

**Q: What if I want to run the scan locally to test?**

Create a `.env` file in your project folder:

```
DATABASE_URL=postgresql://your_neon_connection_string
EMAIL_USER=youremail@gmail.com
EMAIL_PASS=your_app_password
RECEIVER_EMAIL=youremail@gmail.com
```

Then run:

```bash
pip install python-dotenv
python -c "from dotenv import load_dotenv; load_dotenv()"
python scanner_cron.py
```

`curl_cffi` works from your local IP with no blocks — much more reliable than cloud runners.

**Q: What does "Flushed 25 setups to DB" mean in the logs?**

v2 writes to the database every 25 setups found instead of waiting until the end. If the scan crashes at setup #48, you've already saved setups #1–#25 to the database. v1 would have lost everything.

**Q: Can I still trigger the scan from GitHub Actions directly?**

Yes — go to your repo → Actions → Daily NSE Market Scan → **Run workflow** button. This bypasses the Streamlit trigger entirely and is useful for testing.

**Q: What if `GH_TOKEN` expires?**

The cron schedule continues to work (it doesn't use GH_TOKEN). Only the Streamlit trigger button stops working. Just create a new token and update the secret in both GitHub repo secrets and Streamlit secrets.

---

## Summary of all secrets needed

| Secret | Where to set it | Purpose |
|---|---|---|
| `DATABASE_URL` | GitHub Actions + Streamlit | Neon PostgreSQL connection (unchanged) |
| `EMAIL_USER` | GitHub Actions | Gmail sender address (unchanged) |
| `EMAIL_PASS` | GitHub Actions | Gmail app password (unchanged) |
| `RECEIVER_EMAIL` | GitHub Actions | Where to send the report (unchanged) |
| `GH_TOKEN` | **GitHub Actions + Streamlit** | **NEW — triggers scan from UI button** |
| `GH_OWNER` | **Streamlit only** | **NEW — your GitHub username** |
| `GH_REPO` | **Streamlit only** | **NEW — your repo name** |
