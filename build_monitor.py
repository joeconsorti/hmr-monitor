#!/usr/bin/env python3
"""
HMR BTC Cycle Monitor — data fetch + composite score builder.

Pulls on-chain series from the Bitcoin Research Kit (bitview.space) and macro
series from FRED, normalizes each indicator to a 0-100 percentile against its
own full history, computes a composite cycle score for EVERY day in history,
and writes a single monitor.json consumed by the dashboard front end.

Run daily via GitHub Actions. No API keys required for BRK. FRED key optional
(set FRED_API_KEY env var); macro indicators are skipped gracefully without it.
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests

BRK = "https://bitview.space/api"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FNG = "https://api.alternative.me/fng/"
HISTORY_DAYS = 4500          # ~12 years, covers 2 full cycles
LEVEL_HISTORY_DAYS = 5600    # ~15 years, full depth for cost-basis charts
DAILY_TAIL = 400             # days kept at true daily resolution for short ranges
GOLD_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/"
            "GC=F?range=2y&interval=1d")
YT_CHANNEL_ID = "UCw4_-IVRDtkGZkwUmsv1S2A"
YT_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id=" + YT_CHANNEL_ID
YT_VIDEOS_PAGE = "https://www.youtube.com/@JoeConsorti/videos"
SPARKLINE_POINTS = 60        # points kept per indicator for the UI sparkline
TIMEOUT = 60

# ---------------------------------------------------------------------------
# Macro series from FRED. No API key required — the public CSV endpoint is used.
# ---------------------------------------------------------------------------
MACRO = {
    "m2": {
        "fred_id": "M2SL", "label": "US M2 Money Supply", "unit": "B",
        "read": "Total money in the system. It never meaningfully contracts. Every new dollar chases a fixed 21 million.",
    },
    "dxy": {
        "fred_id": "DTWEXBGS", "label": "Dollar Index", "unit": "",
        "read": "The dollar against everything else. Strong dollar drains liquidity. Falling dollar releases it, and bitcoin runs.",
    },
    "us10y": {
        "fred_id": "DGS10", "label": "US 10-Year Yield", "unit": "%",
        "read": "The price of money for the world. Rising yields tighten everything. Falling yields mean the Fed is losing control.",
    },
    "us2y": {
        "fred_id": "DGS2", "label": "US 2-Year Yield", "unit": "%",
        "read": "The market's read on the Fed's next move. Below the funds rate, it is pricing cuts the Fed hasn't admitted.",
    },
    "us30y": {
        "fred_id": "DGS30", "label": "US 30-Year Yield", "unit": "%",
        "read": "Where fiscal credibility gets priced. A rising 30-year while the Fed cuts is the bond market calling the bluff.",
    },
}


# ---------------------------------------------------------------------------
# Indicator definitions
#
# direction:  "high_is_top"  -> a high raw value means late-cycle / top
#             "low_is_top"   -> a low raw value means late-cycle / top
# weight:     relative contribution to the composite
# page/group: routes the card to the right dashboard page and section
# ---------------------------------------------------------------------------
INDICATORS = {
    "mvrv": {
        "series": "mvrv", "label": "MVRV", "direction": "high_is_top",
        "weight": 1.5, "page": "onchain", "group": "profitability", "featured": True,
        "read": "Price against what the average holder paid. Above 3 is top-heavy. Near 1 is where bottoms are built.",
    },
    "sth_mvrv": {
        "series": "sth_mvrv", "label": "STH MVRV", "direction": "high_is_top",
        "weight": 1.0, "page": "onchain", "group": "profitability", "featured": True,
        "read": "Same ratio, recent buyers only. Below 1 means the last five months of demand is underwater.",
    },
    "lth_mvrv": {
        "series": "lth_mvrv", "label": "LTH MVRV", "direction": "high_is_top",
        "weight": 1.0, "page": "onchain", "group": "profitability",
        "read": "Same ratio, long-term holders only. Extreme highs are when old money starts distributing.",
    },
    "nupl": {
        "series": "nupl", "label": "NUPL", "direction": "high_is_top",
        "weight": 1.5, "page": "onchain", "group": "profitability",
        "read": "Unrealized profit in the network. Above 0.75 is euphoria. Below zero is capitulation.",
    },
    "supply_in_profit": {
        "series": "supply_in_profit_share", "label": "Supply in Profit", "direction": "high_is_top",
        "weight": 1.0, "page": "onchain", "group": "profitability", "unit": "%",
        "read": "Share of coins worth more than their last move price. Under 60% is where weak hands finish selling.",
    },
    # Drawdown is DISPLAY-ONLY (weight 0). Percentile-ranking a drawdown does not
    # map cleanly onto cycle position — the asset spends most of its life well off
    # the highs, so the rank is dominated by that. Shown as context, never scored.
    "drawdown": {
        "series": "price_drawdown", "label": "Drawdown from ATH", "direction": "low_is_top",
        "weight": 0.0, "page": "monitor", "group": "price", "unit": "%", "display_only": True,
        "read": "How far price sits below the all-time high. Every cycle bottom has printed between 70% and 85% down. Anything shallower than that historically has not been the floor.",
    },
    "reserve_risk": {
        "series": "reserve_risk", "label": "Reserve Risk", "direction": "high_is_top",
        "weight": 1.5, "page": "onchain", "group": "cohort",
        "read": "Holder conviction against the price to bet alongside it. Low is the best risk-reward this asset offers.",
    },
    "rhodl": {
        "series": "rhodl_ratio", "label": "RHODL Ratio", "direction": "high_is_top",
        "weight": 1.0, "page": "onchain", "group": "cohort",
        "read": "New money versus old money. Spikes mark tops. Low readings mean the tourists have left.",
    },
    # Liveliness is DISPLAY-ONLY (weight 0). It trends structurally upward over
    # time, so a percentile rank against its own history always reads near the
    # top and would drag the composite up permanently. Shown, never scored.
    "liveliness": {
        "series": "liveliness", "label": "Liveliness", "direction": "high_is_top",
        "weight": 0.0, "page": "onchain", "group": "cohort", "display_only": True,
        "read": "Coin-days spent versus held. Rising means holders are distributing. Falling means supply is locking up.",
    },
    "sell_side_risk": {
        "series": "sell_side_risk_ratio_1y", "label": "Sell-Side Risk", "direction": "high_is_top",
        "weight": 0.5, "page": "onchain", "group": "cohort",
        "read": "Realized profit and loss against market size. Low means an exhausted market, right before it turns.",
    },
    "lth_nupl": {
        "series": "lth_nupl", "label": "LTH NUPL", "direction": "high_is_top",
        "weight": 1.0, "page": "onchain", "group": "cohort",
        "read": "Unrealized profit of long-term holders. When it gets extreme, distribution follows.",
    },
    "sth_nupl": {
        "series": "sth_nupl", "label": "STH NUPL", "direction": "high_is_top",
        "weight": 0.5, "page": "onchain", "group": "cohort",
        "read": "Unrealized profit of recent buyers. Negative means the last five months of demand is underwater.",
    },
    "sopr": {
        "series": "sopr_24h", "label": "SOPR", "direction": "high_is_top",
        "weight": 0.5, "page": "onchain", "group": "cohort",
        "read": "Are coins moving at a profit or a loss. Below 1 means the market is selling underwater, a capitulation tell.",
    },
    "sth_sopr": {
        "series": "sth_sopr_24h", "label": "STH SOPR", "direction": "high_is_top",
        "weight": 0.5, "page": "onchain", "group": "cohort",
        "read": "Same, recent buyers only. Persistent sub-1 readings are where short-term pain bottoms out.",
    },
    "lth_sopr": {
        "series": "lth_sopr_24h", "label": "LTH SOPR", "direction": "high_is_top",
        "weight": 0.5, "page": "onchain", "group": "cohort",
        "read": "Same, long-term holders only. Spikes mark old coins taking profit into strength.",
    },
    "puell": {
        "series": "puell_multiple", "label": "Puell Multiple", "direction": "high_is_top",
        "weight": 1.5, "page": "mining", "group": "stress",
        "read": "Miner revenue against its yearly average. Below 1.0, forced selling dries up. That marks every cycle low.",
    },
    "thermocap": {
        "series": "thermo_cap_multiple", "label": "Thermocap Multiple", "direction": "high_is_top",
        "weight": 0.5, "page": "mining", "group": "stress",
        "read": "Price against every dollar ever spent to secure the network. The most conservative valuation bitcoin has.",
    },
}

# Price levels — displayed, not scored
LEVELS = {
    "price": "price",
    "sma_350d": "price_sma_350d",
    "realized": "realized_price",
    "lth_realized": "lth_realized_price",
    "sth_realized": "sth_realized_price",
    "true_market_mean": "true_market_mean",
    "vaulted": "vaulted_price",
}

LEVEL_META = {
    "vaulted":          ("Vaulted Price",     "Long-term holder valuation ceiling"),
    "sma_350d":         ("350-Day MA",        "Accumulation begins below this"),
    "true_market_mean": ("True Market Mean",  "Average price of active capital"),
    "sth_realized":     ("STH Cost Basis",    "Recent buyers underwater below this"),
    "price":            ("BTC SPOT",          "You are here"),
    "realized":         ("Realized Price",    "Average price every coin last moved"),
    "lth_realized":     ("LTH Cost Basis",    "Bottom zone floor"),
}

REGIMES = [
    (0,  15,  "BOTTOM / HARD BUY", "ACCUMULATE"),
    (15, 35,  "DEEP ACCUMULATION", "ACCUMULATE"),
    (35, 65,  "MID-CYCLE",         "HOLD"),
    (65, 85,  "EUPHORIA",          "DISTRIBUTE"),
    (85, 101, "TOP / HARD SELL",   "DISTRIBUTE"),
]


def fetch_fred(series_id):
    """Fetch a FRED series via the public CSV endpoint. No API key needed.
    Returns (dates, values) with missing points dropped."""
    try:
        r = requests.get(FRED_CSV, params={"id": series_id}, timeout=TIMEOUT)
        r.raise_for_status()
        dates, vals = [], []
        for line in r.text.strip().split("\n")[1:]:
            parts = line.split(",")
            if len(parts) < 2:
                continue
            d, v = parts[0], parts[-1].strip()
            if v in (".", "", "NA"):
                continue
            try:
                vals.append(float(v))
                dates.append(d)
            except ValueError:
                continue
        return dates, vals
    except Exception as e:
        print(f"  ! FRED {series_id}: {e}", file=sys.stderr)
        return [], []


def fetch_gold():
    """Spot gold (COMEX front-month) daily closes. Free, no API key.
    Returns a list of closes, oldest first, or [] if unavailable."""
    try:
        r = requests.get(GOLD_URL, timeout=TIMEOUT,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        closes = res["indicators"]["quote"][0]["close"]
        return [c for c in closes if isinstance(c, (int, float))]
    except Exception as e:
        print(f"  ! gold: {e}", file=sys.stderr)
        return []


def _dur_to_seconds(txt):
    """'22:44' or '1:02:33' -> seconds."""
    try:
        parts = [int(p) for p in txt.split(":")]
    except ValueError:
        return None
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return None


def _video_seconds(vid):
    """Runtime of a single video, scraped from its watch page. Fallback only."""
    try:
        r = requests.get("https://www.youtube.com/watch?v=" + vid, timeout=TIMEOUT,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        import re as _re
        m = _re.search(r'"lengthSeconds":"(\d+)"', r.text)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


def _lockup_texts(node, acc):
    """Collect every rendered text string under a YouTube view-model node."""
    if isinstance(node, dict):
        c = node.get("content")
        if isinstance(c, str):
            acc.append(c)
        for v in node.values():
            _lockup_texts(v, acc)
    elif isinstance(node, list):
        for v in node:
            _lockup_texts(v, acc)


def fetch_videos(n=3, min_seconds=181):
    """Latest long-form uploads from the channel's public /videos page.

    Shorts are excluded by runtime: anything <= 3 minutes is dropped. The page
    lists ~30 uploads with durations, so there is always enough long-form to
    fill the strip. No API key, one request.
    Returns [{id, title, published, url, thumb, seconds}] or [].
    """
    import re as _re
    try:
        r = requests.get(YT_VIDEOS_PAGE, timeout=TIMEOUT,
                         headers={"User-Agent": "Mozilla/5.0",
                                  "Accept-Language": "en-US"})
        r.raise_for_status()
        html = r.text

        # duration badge sits next to each videoId in the raw payload
        dmap = {}
        for vid, dur in _re.findall(
                r'"videoId":"([\w-]{11})".*?"text":"(\d+:\d+(?::\d+)?)"', html):
            dmap.setdefault(vid, dur)

        blob = _re.search(r"var ytInitialData = (\{.*?\});</script>", html)
        if not blob:
            raise ValueError("ytInitialData not found")
        data = json.loads(blob.group(1))

        lockups = []

        def walk(o):
            if isinstance(o, dict):
                if "lockupViewModel" in o:
                    lockups.append(o["lockupViewModel"])
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(data)

        rows = []
        for lk in lockups:
            vid = lk.get("contentId")
            dur = dmap.get(vid)
            if not vid or not dur:
                continue
            secs = _dur_to_seconds(dur)
            if secs is None or secs < min_seconds:
                continue                      # Short
            acc = []
            _lockup_texts(lk.get("metadata", {}), acc)
            title = acc[0] if acc else ""
            published = next((a for a in acc if "ago" in a), "")
            rows.append({
                "id": vid,
                "title": title,
                "published": published,       # e.g. "3 days ago"
                "url": "https://www.youtube.com/watch?v=" + vid,
                "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                "seconds": secs,
            })
            if len(rows) >= n:
                break
        return rows
    except Exception as e:
        print(f"  ! videos: {e}", file=sys.stderr)
        return []


def fetch_fear_greed():
    """Fetch the full Fear & Greed history from alternative.me. No key needed."""
    try:
        r = requests.get(FNG, params={"limit": 0}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json().get("data", [])
        # API returns newest-first; flip to chronological
        vals = [int(x["value"]) for x in reversed(data)]
        latest = data[0] if data else None
        return vals, (latest["value_classification"] if latest else None)
    except Exception as e:
        print(f"  ! Fear & Greed: {e}", file=sys.stderr)
        return [], None


def pct_change(vals, periods):
    """Percent change over N periods back."""
    if len(vals) <= periods:
        return None
    old = vals[-1 - periods]
    if not old:
        return None
    return round(100.0 * (vals[-1] - old) / abs(old), 2)


def fetch_series(name, days=HISTORY_DAYS):
    """Fetch a daily series from BRK. Returns list of floats (None-stripped tail)."""
    url = f"{BRK}/series/{name}/date/data"
    try:
        r = requests.get(url, params={"from": -days}, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  ! {name}: {e}", file=sys.stderr)
        return None


def fetch_dates(days=HISTORY_DAYS):
    """Fetch the BRK date index aligned to the daily series (ISO date strings)."""
    url = f"{BRK}/series/date/date/data"
    try:
        r = requests.get(url, params={"from": -days}, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  ! dates: {e}", file=sys.stderr)
        return None


def dated_downsample(dates, values, target=200):
    """Zip dates+values (tail-aligned), drop Nones, downsample to ~target points.
    Returns list of {t: 'YYYY-MM-DD', v: float} for Lightweight Charts."""
    if not dates or not values:
        return []
    # align on the shorter tail
    n = min(len(dates), len(values))
    ds, vs = dates[-n:], values[-n:]
    pairs = [(d, v) for d, v in zip(ds, vs) if isinstance(v, (int, float))]
    if not pairs:
        return []
    step = max(1, len(pairs) // target)
    out = [{"t": d, "v": round(v, 6)} for d, v in pairs[::step]]
    # always include the final point
    if out and out[-1]["t"] != pairs[-1][0]:
        d, v = pairs[-1]
        out.append({"t": d, "v": round(v, 6)})
    return out


def percentile_rank(value, history):
    """What % of historical values sit below `value`. Returns 0-100."""
    clean = [v for v in history if isinstance(v, (int, float))]
    if not clean:
        return None
    below = sum(1 for v in clean if v < value)
    return round(100.0 * below / len(clean), 1)


def quantiles(history, n=201):
    """Return an n-point sorted quantile array of `history`, from the 0th to the
    100th percentile. The browser ranks a live value against this array to
    reproduce the exact percentile this script computes, without shipping the
    full multi-thousand-point series. 201 points = 0.5% resolution."""
    clean = sorted(v for v in history if isinstance(v, (int, float)))
    if not clean:
        return None
    m = len(clean)
    out = []
    for i in range(n):
        pos = i / (n - 1) * (m - 1)
        lo = int(pos)
        hi = min(lo + 1, m - 1)
        frac = pos - lo
        out.append(clean[lo] + (clean[hi] - clean[lo]) * frac)
    return [round(v, 8) for v in out]


def to_score(value, history, direction):
    """Normalize a raw indicator value to 0-100 where 100 = cycle top."""
    p = percentile_rank(value, history)
    if p is None:
        return None
    return p if direction == "high_is_top" else round(100.0 - p, 1)


def regime_for(score):
    for lo, hi, label, verdict in REGIMES:
        if lo <= score < hi:
            return label, verdict
    return "MID-CYCLE", "HOLD"


def build():
    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Bitcoin Research Kit (bitview.space) + FRED",
        "history_window_days": HISTORY_DAYS,
    }

    # ---- date index (aligns every series to ISO dates for charts) ---------
    print("Fetching date index...")
    all_dates = fetch_dates(days=LEVEL_HISTORY_DAYS) or []
    print(f"  ok date index {len(all_dates)} pts")

    # ---- fetch every indicator series -------------------------------------
    print("Fetching indicator series...")
    raw = {}
    for key, cfg in INDICATORS.items():
        data = fetch_series(cfg["series"])
        if data:
            raw[key] = data
            print(f"  ok {cfg['series']:28} {len(data)} pts")

    # ---- fetch price levels ------------------------------------------------
    # Full available history (~15 years) so the Levels and Monitor charts can
    # plot real historical cost-basis curves, not flat snapshot lines.
    print("Fetching price levels...")
    LEVEL_DAYS = LEVEL_HISTORY_DAYS
    levels_raw = {}
    for key, series in LEVELS.items():
        data = fetch_series(series, days=LEVEL_DAYS)
        if data:
            levels_raw[key] = data
            print(f"  ok {series:28} {len(data)} pts")

    # ---- current values, percentiles, per-indicator payload ----------------
    indicators = {}
    weighted_sum = 0.0
    weight_total = 0.0
    bottom_quartile = 0

    for key, cfg in INDICATORS.items():
        if key not in raw:
            continue
        series = raw[key]
        clean = [v for v in series if isinstance(v, (int, float))]
        if not clean:
            continue

        current = clean[-1]
        score = to_score(current, clean, cfg["direction"])
        pct = percentile_rank(current, clean)
        if score is None:
            continue

        # 30-day direction
        prev = clean[-31] if len(clean) > 31 else clean[0]
        trend = "down" if current < prev else ("up" if current > prev else "flat")

        w = cfg.get("weight", 1.0)
        # display-only indicators (weight 0) are shown but never scored
        if w > 0:
            if score < 25:
                bottom_quartile += 1
            weighted_sum += score * w
            weight_total += w

        # dated series for this indicator's own chart (chart-per-indicator on
        # the On-Chain and Mining pages, and the sparkline on every card).
        # ~3 years, ~120 points. This supersedes the old flat sparkline array.
        chart = dated_downsample(all_dates, series[-1100:], target=120)

        indicators[key] = {
            "label": cfg["label"],
            "value": round(current, 8),
            "unit": cfg.get("unit", ""),
            "score": score,
            "percentile": pct,
            "trend": trend,
            "weight": w,
            "page": cfg["page"],
            "group": cfg["group"],
            "read": cfg["read"],
            "featured": cfg.get("featured", False),
            "chart": chart,
        }

    composite = round(weighted_sum / weight_total) if weight_total else 50
    regime, verdict = regime_for(composite)

    # ---- historical composite (for the score history chart) ---------------
    print("Computing historical composite score...")
    series_lists = {k: [v if isinstance(v, (int, float)) else None for v in raw[k]]
                    for k in raw}
    n = min(len(v) for v in series_lists.values())
    history_scores = []
    STRIDE = 7   # weekly resolution keeps the file small
    for i in range(0, n, STRIDE):
        ws, wt = 0.0, 0.0
        for key, cfg in INDICATORS.items():
            if key not in series_lists:
                continue
            if cfg.get("weight", 1.0) <= 0:      # display-only, never scored
                continue
            val = series_lists[key][i]
            if val is None:
                continue
            hist = [v for v in series_lists[key][:i + 1] if v is not None]
            if len(hist) < 100:      # need enough history to rank against
                continue
            s = to_score(val, hist, cfg["direction"])
            if s is None:
                continue
            w = cfg.get("weight", 1.0)
            ws += s * w
            wt += w
        if wt:
            history_scores.append(round(ws / wt, 1))

    out["score"] = {
        "composite": composite,
        "regime": regime,
        "verdict": verdict,
        "in_bottom_quartile": bottom_quartile,
        "total_indicators": sum(1 for v in indicators.values() if v["weight"] > 0),
        "total_displayed": len(indicators),
        "history": history_scores,
        "history_stride_days": STRIDE,
    }

    # 30-day delta on the composite
    if len(history_scores) >= 5:
        out["score"]["delta_30d"] = round(composite - history_scores[-5], 1)

    out["indicators"] = indicators

    # ---- levels ------------------------------------------------------------
    levels = {}
    for key, data in levels_raw.items():
        clean = [v for v in data if isinstance(v, (int, float))]
        if clean:
            levels[key] = round(clean[-1], 2)

    spot = levels.get("price")
    levels_table = []
    if spot:
        for key, val in levels.items():
            label, meaning = LEVEL_META.get(key, (key, ""))
            levels_table.append({
                "key": key,
                "label": label,
                "value": val,
                "vs_spot_pct": round(100.0 * (val - spot) / spot, 1),
                "meaning": meaning,
            })
        levels_table.sort(key=lambda x: -x["value"])

    out["levels"] = levels
    out["levels_table"] = levels_table

    # ---- dated level series (Levels + Monitor cost-basis charts) ----------
    # Price plus each cost-basis model as its own line over the full ~15-year
    # date axis. Powers the HISTORICAL mode of the cost-basis toggle.
    # Two resolutions per model:
    #   points       ~430 pts across the full ~15y span (long ranges)
    #   points_daily  every day for the last ~2y (1W/1M/3M/6M/1Y ranges)
    # The front end picks whichever fits the selected range so short windows
    # always render true daily candles instead of a sparse downsample.
    level_series = {}
    for key, data in levels_raw.items():
        ser = dated_downsample(all_dates, data, target=420)
        if ser:
            label, meaning = LEVEL_META.get(key, (key, ""))
            daily = dated_downsample(all_dates[-DAILY_TAIL:], data[-DAILY_TAIL:],
                                     target=DAILY_TAIL)
            level_series[key] = {"label": label, "points": ser,
                                 "points_daily": daily}
    out["level_series"] = level_series

    # ---- price chart series for the hero (dated, for the monitor page) -----
    if "price" in levels_raw:
        # dated series for the monitor price chart
        out["price_series_dated"] = dated_downsample(all_dates, levels_raw["price"], target=420)
        out["price_series_daily"] = dated_downsample(
            all_dates[-DAILY_TAIL:], levels_raw["price"][-DAILY_TAIL:], target=DAILY_TAIL)

    # ---- cycle clock -------------------------------------------------------
    if "price" in levels_raw:
        pr = [v for v in levels_raw["price"] if isinstance(v, (int, float))]
        if pr:
            ath = max(pr)
            ath_idx = len(pr) - 1 - pr[::-1].index(ath)
            out["cycle_clock"] = {
                "days_since_ath": len(pr) - 1 - ath_idx,
                "ath": round(ath, 2),
                "note": "2018 low = ATH+363d · 2022 low = ATH+376d",
            }

    # ---- Fear & Greed (scored, sentiment leg) ------------------------------
    print("Fetching Fear & Greed...")
    fng_hist, fng_class = fetch_fear_greed()
    if fng_hist:
        fng_now = fng_hist[-1]
        fng_pct = percentile_rank(fng_now, fng_hist)
        prev = fng_hist[-31] if len(fng_hist) > 31 else fng_hist[0]
        # F&G has its own (shorter) date axis; align to the tail of the index.
        fng_chart = dated_downsample(all_dates, fng_hist, target=120)
        indicators["fear_greed"] = {
            "label": "Fear & Greed",
            "value": fng_now,
            "unit": "",
            "score": fng_pct,          # high greed = top, so percentile maps directly
            "percentile": fng_pct,
            "trend": "down" if fng_now < prev else ("up" if fng_now > prev else "flat"),
            "weight": 1.0,
            "page": "monitor",
            "group": "sentiment",
            "classification": fng_class,
            "read": "Crowd sentiment in one number. Extreme fear is where the best entries are made. A contrarian gauge.",
            "chart": fng_chart,
        }
        # fold into the composite
        weighted_sum += fng_pct * 1.0
        weight_total += 1.0
        if fng_pct < 25:
            bottom_quartile += 1
        composite = round(weighted_sum / weight_total)
        regime, verdict = regime_for(composite)
        out["score"]["composite"] = composite
        out["score"]["regime"] = regime
        out["score"]["verdict"] = verdict
        out["score"]["in_bottom_quartile"] = bottom_quartile
        out["score"]["total_indicators"] = sum(
            1 for v in indicators.values() if v["weight"] > 0)
        out["score"]["total_displayed"] = len(indicators)
        print(f"  ok Fear & Greed {fng_now} ({fng_class}) · {len(fng_hist)} pts")

    # ---- macro (FRED, no API key required) --------------------------------
    print("Fetching macro series from FRED...")
    macro = {}
    for key, cfg in MACRO.items():
        dates, vals = fetch_fred(cfg["fred_id"])
        if not vals:
            continue
        step = max(1, len(vals) // SPARKLINE_POINTS)
        macro[key] = {
            "label": cfg["label"],
            "value": round(vals[-1], 4),
            "unit": cfg["unit"],
            "as_of": dates[-1] if dates else None,
            "chg_30d": pct_change(vals, 21),      # ~21 business days
            "chg_ytd": pct_change(vals, 252),     # ~1 trading year
            "read": cfg["read"],
            "sparkline": [round(v, 4) for v in vals[::step][-SPARKLINE_POINTS:]],
        }
        print(f"  ok {cfg['fred_id']:10} {vals[-1]}")
    out["macro"] = macro

    # ---- cross-asset watchlist --------------------------------------------
    watchlist = []
    if spot and "price" in levels_raw:
        pr = [v for v in levels_raw["price"] if isinstance(v, (int, float))]
        watchlist.append({"ticker": "BTC", "price": spot,
                          "d30": pct_change(pr, 30),
                          "ytd": pct_change(pr, 200)})
    # Gold sits directly under BTC — the comparison the audience actually cares
    # about. Sourced separately because FRED's LBMA gold series were retired.
    print("Fetching gold...")
    gold = fetch_gold()
    if gold:
        watchlist.append({"ticker": "GOLD", "price": round(gold[-1], 2),
                          "d30": pct_change(gold, 21),
                          "ytd": pct_change(gold, 252)})
        print(f"  ok GOLD       {round(gold[-1], 2)}")

    for key, tick in (("dxy", "DXY"), ("us10y", "US 10Y"), ("us2y", "US 2Y")):
        if key in macro:
            m = macro[key]
            watchlist.append({"ticker": tick, "price": m["value"],
                              "d30": m["chg_30d"], "ytd": m["chg_ytd"]})
    out["watchlist"] = watchlist

    # ---- latest uploads (public RSS, no API key) --------------------------
    print("Fetching latest videos...")
    videos = fetch_videos(3)
    out["videos"] = videos
    for v in videos:
        mins = v.get("seconds", 0) // 60
        print(f"  ok {v['published']}  {mins:>3}m  {v['title'][:46]}")

    # ---- distributions + live_series (browser-side live recompute) --------
    # The dashboard polls BRK directly every 5 minutes, takes the latest value
    # of each series, and ranks it against the quantile array below to rebuild
    # the exact percentile + composite this script produces. FRED is CORS-blocked
    # so macro stays on the daily Action; everything here is CORS-open on BRK.
    # This block runs AFTER Fear & Greed is folded into `indicators` so the
    # sentiment leg is included in the live composite exactly as scored here.
    print("Building distributions for live recompute...")
    distributions = {}
    live_series = {}
    for key, cfg in INDICATORS.items():
        if key not in raw or key not in indicators:
            continue
        clean = [v for v in raw[key] if isinstance(v, (int, float))]
        q = quantiles(clean)
        if not q:
            continue
        distributions[key] = {
            "q": q,
            "direction": cfg["direction"],
            "weight": cfg.get("weight", 1.0),
            "unit": cfg.get("unit", ""),
        }
        live_series[key] = cfg["series"]

    # Fear & Greed distribution (scored; alternative.me is also CORS-open).
    if "fear_greed" in indicators and fng_hist:
        q = quantiles(fng_hist)
        if q:
            distributions["fear_greed"] = {
                "q": q, "direction": "high_is_top",
                "weight": indicators["fear_greed"]["weight"], "unit": "",
            }

    out["distributions"] = distributions
    out["live_series"] = live_series
    out["live_levels"] = dict(LEVELS)
    out["live_endpoints"] = {
        "brk_series": BRK + "/series/{name}/date/data?from=-1",
        "brk_price": BRK + "/series/price/date/data?from=-1",
        "fng": "https://api.alternative.me/fng/?limit=1",
    }

    return out


if __name__ == "__main__":
    data = build()
    with open("monitor.json", "w") as f:
        json.dump(data, f, indent=1)
    s = data["score"]
    print()
    print("=" * 58)
    print(f"  COMPOSITE SCORE : {s['composite']}/100")
    print(f"  REGIME          : {s['regime']}")
    print(f"  VERDICT         : {s['verdict']}")
    print(f"  BOTTOM QUARTILE : {s['in_bottom_quartile']} of {s['total_indicators']}")
    print(f"  30D DELTA       : {s.get('delta_30d','n/a')}")
    print(f"  HISTORY POINTS  : {len(s['history'])}")
    print("=" * 58)
