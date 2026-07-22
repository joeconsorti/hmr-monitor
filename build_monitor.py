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
SPARKLINE_POINTS = 60        # points kept per indicator for the UI sparkline
TIMEOUT = 60

# ---------------------------------------------------------------------------
# Macro series from FRED. No API key required — the public CSV endpoint is used.
# ---------------------------------------------------------------------------
MACRO = {
    "m2": {
        "fred_id": "M2SL", "label": "US M2 Money Supply", "unit": "B",
        "read": "The total supply of money in the system. It has never meaningfully contracted, and it is not going to. Every dollar printed is a dollar chasing a fixed 21 million. This is the whole reason bitcoin exists.",
    },
    "dxy": {
        "fred_id": "DTWEXBGS", "label": "Dollar Index", "unit": "",
        "read": "The dollar against everything else. A strong dollar drains liquidity out of risk assets and holds bitcoin down. A falling dollar releases that pressure, and bitcoin is the highest-beta expression of it.",
    },
    "us10y": {
        "fred_id": "DGS10", "label": "US 10-Year Yield", "unit": "%",
        "read": "The price of money for the entire world. Rising yields mean tighter conditions and pressure on every asset priced off duration. Falling yields mean the Fed is losing control of the cost of debt, which historically ends one way.",
    },
    "us2y": {
        "fred_id": "DGS2", "label": "US 2-Year Yield", "unit": "%",
        "read": "The market's read on where the Fed is going next. When it falls below the funds rate, the market is pricing cuts before the Fed admits them.",
    },
    "us30y": {
        "fred_id": "DGS30", "label": "US 30-Year Yield", "unit": "%",
        "read": "The long end is where fiscal credibility gets priced. A rising 30-year while the Fed cuts is the bond market saying it does not believe the story.",
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
        "weight": 1.5, "page": "onchain", "group": "profitability",
        "read": "Market value against what everyone actually paid. Above 3 means the average holder is sitting on huge unrealized gains and the market is top-heavy. Near 1 means the average holder is roughly breakeven, and that is where every cycle bottom has been built.",
    },
    "nupl": {
        "series": "nupl", "label": "NUPL", "direction": "high_is_top",
        "weight": 1.5, "page": "onchain", "group": "profitability",
        "read": "How much unrealized profit is sitting in the network right now. Above 0.75 is euphoria and it never lasts. Below zero means the average coin is underwater, which is the definition of capitulation.",
    },
    "supply_in_profit": {
        "series": "supply_in_profit_share", "label": "Supply in Profit", "direction": "high_is_top",
        "weight": 1.0, "page": "onchain", "group": "profitability", "unit": "%",
        "read": "The share of all bitcoin currently worth more than the price it last moved at. When this drops under 60%, four out of every ten coins are underwater. That is when weak hands finish selling.",
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
        "read": "Confidence of long-term holders against the price you pay to bet alongside them. Low readings mean conviction is high and price is low, which is the best risk-reward setup that exists in this asset.",
    },
    "rhodl": {
        "series": "rhodl_ratio", "label": "RHODL Ratio", "direction": "high_is_top",
        "weight": 1.0, "page": "onchain", "group": "cohort",
        "read": "Compares what new money is doing against what old money is doing. Spikes mark tops, when new buyers are piling in at the worst possible moment. Low readings mean the tourists have left.",
    },
    # Liveliness is DISPLAY-ONLY (weight 0). It trends structurally upward over
    # time, so a percentile rank against its own history always reads near the
    # top and would drag the composite up permanently. Shown, never scored.
    "liveliness": {
        "series": "liveliness", "label": "Liveliness", "direction": "high_is_top",
        "weight": 0.0, "page": "onchain", "group": "cohort", "display_only": True,
        "read": "How much of the network's coin-days are being spent versus held. Rising means old coins are moving and holders are distributing. Falling means the supply is going dormant and getting locked up.",
    },
    "sell_side_risk": {
        "series": "sell_side_risk_ratio_1y", "label": "Sell-Side Risk", "direction": "high_is_top",
        "weight": 0.5, "page": "onchain", "group": "cohort",
        "read": "How much profit and loss is actually being realized against the size of the market. Low readings mean nobody is transacting, which is what an exhausted market looks like right before it turns.",
    },
    "lth_nupl": {
        "series": "lth_nupl", "label": "LTH NUPL", "direction": "high_is_top",
        "weight": 1.0, "page": "onchain", "group": "cohort",
        "read": "Unrealized profit held by long-term holders. These are the people who decide when a cycle actually ends. When their profit gets extreme, distribution follows.",
    },
    "sth_nupl": {
        "series": "sth_nupl", "label": "STH NUPL", "direction": "high_is_top",
        "weight": 0.5, "page": "onchain", "group": "cohort",
        "read": "Unrealized profit held by recent buyers. Negative means everyone who bought in the last five months is underwater, and their pain is what creates the capitulation wick.",
    },
    "puell": {
        "series": "puell_multiple", "label": "Puell Multiple", "direction": "high_is_top",
        "weight": 1.5, "page": "mining", "group": "stress",
        "read": "Miner revenue against its own yearly average. Miners are the only structural sellers in this market. When their revenue compresses below 1.0, forced selling dries up, and that has marked the low of every single cycle.",
    },
    "thermocap": {
        "series": "thermo_cap_multiple", "label": "Thermocap Multiple", "direction": "high_is_top",
        "weight": 0.5, "page": "mining", "group": "stress",
        "read": "Price against every dollar ever paid to secure the network. It is the most conservative valuation model that exists for bitcoin, and it tells you whether the market is paying a reasonable multiple on the security budget.",
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


def percentile_rank(value, history):
    """What % of historical values sit below `value`. Returns 0-100."""
    clean = [v for v in history if isinstance(v, (int, float))]
    if not clean:
        return None
    below = sum(1 for v in clean if v < value)
    return round(100.0 * below / len(clean), 1)


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

    # ---- fetch every indicator series -------------------------------------
    print("Fetching indicator series...")
    raw = {}
    for key, cfg in INDICATORS.items():
        data = fetch_series(cfg["series"])
        if data:
            raw[key] = data
            print(f"  ok {cfg['series']:28} {len(data)} pts")

    # ---- fetch price levels ------------------------------------------------
    print("Fetching price levels...")
    levels_raw = {}
    for key, series in LEVELS.items():
        data = fetch_series(series, days=400)
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

        # downsample for sparkline
        step = max(1, len(clean) // SPARKLINE_POINTS)
        spark = clean[::step][-SPARKLINE_POINTS:]

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
            "sparkline": [round(v, 6) for v in spark],
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

    # ---- price chart series for the hero -----------------------------------
    if "price" in levels_raw:
        pr = [v for v in levels_raw["price"] if isinstance(v, (int, float))]
        step = max(1, len(pr) // 120)
        out["price_series"] = [round(v, 2) for v in pr[::step]]

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
        step = max(1, len(fng_hist) // SPARKLINE_POINTS)
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
            "read": "Crowd sentiment in a single number. Extreme fear is where the best entries have historically been made, and extreme greed is where the worst ones are. It is a contrarian gauge, not a directional one.",
            "sparkline": fng_hist[::step][-SPARKLINE_POINTS:],
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
    for key, tick in (("dxy", "DXY"), ("us10y", "US 10Y"), ("us2y", "US 2Y")):
        if key in macro:
            m = macro[key]
            watchlist.append({"ticker": tick, "price": m["value"],
                              "d30": m["chg_30d"], "ytd": m["chg_ytd"]})
    out["watchlist"] = watchlist

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
