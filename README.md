# HMR BTC Cycle Monitor

Data engine for The Hard Money Room dashboard.

## What it does
`build_monitor.py` pulls ~12 years of Bitcoin on-chain history from the
[Bitcoin Research Kit](https://bitview.space) (free, no API key, no rate limit),
normalizes each indicator to a 0-100 percentile against its own full history,
computes a weighted composite cycle score, and writes `monitor.json`.

The GitHub Action runs it daily and commits the result. The dashboard front end
reads `monitor.json` directly — no database, no server, no cost.

## Scored indicators (11)
MVRV · NUPL · Supply in Profit · Reserve Risk · RHODL · Sell-Side Risk ·
LTH NUPL · STH NUPL · Puell Multiple · Thermocap Multiple · Fear & Greed

## Macro (displayed, not scored)
US M2 · Dollar Index · US 2Y / 10Y / 30Y yields — pulled from FRED's public
CSV endpoint. **No API key required.**

## Data sources (all free, no keys)
| Source | What |
|---|---|
| [Bitcoin Research Kit](https://bitview.space) | All on-chain series, 4,500 days |
| [FRED](https://fred.stlouisfed.org) | M2, DXY, Treasury yields |
| [alternative.me](https://alternative.me/crypto/fear-and-greed-index/) | Fear & Greed, 3,090 days |

## Display-only (not scored)
- **Liveliness** — trends structurally upward over time, so a percentile rank
  always reads near the top and would permanently inflate the composite.
- **Drawdown from ATH** — the asset spends most of its life well off the highs,
  so the percentile rank is dominated by that rather than cycle position.

## Score bands
| Range | Regime | Verdict |
|---|---|---|
| 0-15 | BOTTOM / HARD BUY | ACCUMULATE |
| 15-35 | DEEP ACCUMULATION | ACCUMULATE |
| 35-65 | MID-CYCLE | HOLD |
| 65-85 | EUPHORIA | DISTRIBUTE |
| 85-100 | TOP / HARD SELL | DISTRIBUTE |

## Files
| File | What |
|---|---|
| `build_monitor.py` | Fetches all data, computes the score, writes `monitor.json` |
| `monitor.json` | The data payload the dashboard reads (~30 KB) |
| `index.html` | The five-page dashboard. Self-contained, no dependencies. |
| `.github/workflows/daily.yml` | Runs the build daily at 13:15 UTC (~9:15 AM ET) |
| `CNAME` | Custom domain for GitHub Pages |

## Deploy

**1. Push to GitHub**
```
git init && git add . && git commit -m "initial"
git remote add origin https://github.com/YOURNAME/hmr-monitor.git
git push -u origin main
```

**2. Allow the Action to commit data**
Settings → Actions → General → Workflow permissions → **Read and write** → Save

**3. Turn on Pages**
Settings → Pages → Source: **Deploy from a branch** → Branch: `main` / root → Save

**4. Point the subdomain**
At your DNS registrar add a CNAME record:
```
monitor   CNAME   YOURNAME.github.io
```
The `CNAME` file in this repo already declares `monitor.joeconsorti.com` — edit it
if you want a different subdomain.

**5. Test the data job**
Actions tab → "Build BTC Cycle Monitor" → **Run workflow**

After that it runs itself. Every morning the Action refreshes `monitor.json`,
commits it, and Pages redeploys automatically. No server, no database, no cost.

## Local preview
```
python3 build_monitor.py && python3 -m http.server 8000
```
Then open http://localhost:8000

## Still to add
- "What changed today" diff against the previous day's file
- Alert triggers (score crosses 15/85, price enters bottom zone)
- Gold / S&P / BTC-GOLD ratio in the watchlist

Educational only. Not financial advice.
