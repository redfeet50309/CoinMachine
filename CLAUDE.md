# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CoinMachine is a personal Taiwan stock technical-indicator tracker. A Python backend pulls daily OHLCV from TWSE/TPEx, computes indicators (MA, MACD, RSI, Bollinger), runs rule-based signal analysis, writes JSON to `data/`, and pushes a LINE summary. A static frontend hosted on GitHub Pages reads the committed JSON.

The full nightly run is triggered by **Windows Task Scheduler at 22:00 weekdays — not GitHub Actions**, because TWSE/TPEx geo-block non-Taiwan IPs.

## Commands

```bash
# Install Python deps
pip install -r scripts/requirements.txt

# Full sweep (all watchlist stocks)
python scripts/build_dataset.py

# Specific stocks only (skips LINE notify)
python scripts/build_dataset.py 2330 8299

# Run all tests
pytest tests/

# Single test
pytest tests/test_indicators.py::test_name -v

# Local frontend (from repo root)
python -m http.server 8000

# LINE notification dry-run (prints, doesn't push)
py scripts/notify.py --dry-run
```

PowerShell-only:

```powershell
# Register Windows Task Scheduler entry (one-time setup)
.\scripts\register_task.ps1

# Manually trigger the scheduled task
Start-ScheduledTask -TaskName 'CoinMachine-daily'

# Manual full run with the same wrapper as the scheduled job
.\scripts\run_local.ps1

# Inspect last scheduled run
Get-Content data\last_run.log -Tail 30
```

## Architecture

**Two-process split connected by git:**

1. **Backend (`scripts/`)** — Python, runs on a Taiwan-IP machine. Pipeline:
   `build_dataset.py` orchestrates → `fetch_twse.py` pulls OHLCV → `indicators.py` computes MA/EMA/MACD/RSI/BB/divergences → `analyze.py` produces signal labels → JSON written under `data/stocks/{id}.json` → `notify.py` pushes LINE summary.
2. **Frontend (root + `app.js`)** — Alpine.js + Lightweight Charts. Reads same-origin `data/*.json`. Writes **only** `data/watchlist.json` via GitHub Contents API using the user's PAT (stored in browser localStorage; never sent to a server).

**Data flow is one-way through git:**

- Backend writes `data/stocks/{id}.json`, `data/index.json`, `data/meta.json`, `data/notify_state.json` → `git push origin main`
- Frontend writes `data/watchlist.json` via GitHub Contents API (PAT scope: this repo only, Contents read/write)
- GitHub Pages deploys on push (see `.github/workflows/pages.yml`)

**Fetch strategy** — Both TWSE and TPEx use a layered pattern:
`(per-stock month endpoint for backfill) + (batch snapshot endpoint for latest day, defensive)`.
The `seen` date set in `update_stock` prevents duplicate rows when both sources return the same day. TWSE additionally probes `is_twse_legacy_alive()` per run because the legacy endpoint has flaked from US-CDN since mid-2026.

**Indicator math** lives in `indicators.py`:
- EMA uses `adjust=False` (recursive form, matches Taiwan broker convention)
- Bollinger uses population std (`ddof=0`, matches TradingView)
- Threshold constants are centralised in `scripts/config.py`
- **Changing any signal definition requires bumping `RULE_VERSION` in `config.py`** so the frontend can invalidate cached state

**Signal pipeline:** `analyze.py` emits string labels (`ma_trend`, `macd_zone`, `pv_category`, …) → `rules.js` maps labels → CSS class → card colour. LINE message templates live in `notify.py`.

## Project-Specific Conventions

- **Geo-block**: TWSE/TPEx reject non-Taiwan IPs (HTTP 404 / Cloudflare 530). Anything that hits these endpoints must run locally or on a Taiwan-hosted machine. CI cannot fetch market data — that's why the cron lives in Windows Task Scheduler, not GitHub Actions.
- **Volume units differ across endpoints**: TPEx **legacy** returns 張 (multiply by 1000 for shares); TPEx **OpenAPI batch** returns shares directly. TWSE both endpoints return shares. See `_parse_tpex` vs `fetch_tpex_latest_all` for the divergence.
- **PowerShell console encoding (cp950)**: `print(chinese_string)` may render mojibake during debug, but actual JSON I/O is UTF-8 and stored correctly. Don't "fix" encoding based on console display alone — verify the bytes.
- **`'---'` placeholder**: TPEx OpenAPI uses `'---'` (sometimes with leading space) for OHLC of illiquid rows. `_to_float` returns NaN for any dash-only string; `fetch_tpex_latest_all` skips rows whose Close is NaN.
- **ROC date formats are not uniform**: legacy endpoints use `115/03/02` (slashes), OpenAPI uses `1150302` (concatenated). `_roc_to_iso` handles the former; the latter is parsed inline by slicing.
- **Known limitation: ex-dividend (除權息) not adjusted**. Causes MA/MACD/divergence signals to spike falsely around ex-dividend days. Phase 3 plan in `docs/data-sources.md` § A is to add `adj_close` alongside `close`.
- **PR workflow**: `main` is protected — direct push is blocked. Land changes via feature branch + `gh pr create` + squash-merge.

## Reference

- `README.md` — user-facing setup, full formula list, signal threshold table, LINE setup
- `docs/data-sources.md` — complete TWSE/TPEx OpenAPI endpoint catalog organised by category (除權息 / 法人 / 融資融券 / 基本面 / 警示處置), implementation gotchas, Phase 3 priorities
- `scripts/config.py` — single source of truth for thresholds, endpoint URLs, periods, retry settings

---

## Behavioral Rules

Source: Karpathy's 4 rules (via Forrest Chang) + Mnimiy's 8 extended rules (May 2026).

## Rule 1 — Think Before Coding
State assumptions explicitly. If uncertain, ask rather than guess.
Present multiple interpretations when ambiguity exists.
Push back when a simpler approach exists.
Stop when confused. Name what's unclear.

## Rule 2 — Simplicity First
Minimum code that solves the problem. Nothing speculative.
No features beyond what was asked. No abstractions for single-use code.
Test: would a senior engineer say this is overcomplicated? If yes, simplify.

## Rule 3 — Surgical Changes
Touch only what you must. Clean up only your own mess.
Don't "improve" adjacent code, comments, or formatting.
Don't refactor what isn't broken. Match existing style.

## Rule 4 — Goal-Driven Execution
Define success criteria. Loop until verified.
Don't follow steps. Define success and iterate.
Strong success criteria let you loop independently.

## Rule 5 — Use the model only for judgment calls
Use me for: classification, drafting, summarization, extraction.
Do NOT use me for: routing, retries, deterministic transforms.
If code can answer, code answers.

## Rule 6 — Token budgets are not advisory
Per-task: 4,000 tokens. Per-session: 30,000 tokens.
If approaching budget, summarize and start fresh.
Surface the breach. Do not silently overrun.

## Rule 7 — Surface conflicts, don't average them
If two patterns contradict, pick one (more recent / more tested).
Explain why. Flag the other for cleanup.
Don't blend conflicting patterns.

## Rule 8 — Read before you write
Before adding code, read exports, immediate callers, shared utilities.
"Looks orthogonal" is dangerous. If unsure why code is structured a way, ask.

## Rule 9 — Tests verify intent, not just behavior
Tests must encode WHY behavior matters, not just WHAT it does.
A test that can't fail when business logic changes is wrong.

## Rule 10 — Checkpoint after every significant step
Summarize what was done, what's verified, what's left.
Don't continue from a state you can't describe back.
If you lose track, stop and restate.

## Rule 11 — Match the codebase's conventions, even if you disagree
Conformance > taste inside the codebase.
If you genuinely think a convention is harmful, surface it. Don't fork silently.

## Rule 12 — Fail loud
"Completed" is wrong if anything was skipped silently.
"Tests pass" is wrong if any were skipped.
Default to surfacing uncertainty, not hiding it.
