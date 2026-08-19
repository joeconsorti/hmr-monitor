"""
collect_data.py — pulls every data point the newsletter might use.
Same free sources as the monitor: BRK (on-chain), Yahoo (macro), alternative.me
(Fear & Greed), and the live monitor.json (composite score + levels).

Returns one dict. Nothing here decides what goes in the newsletter — that's
select.py's job. This just gathers everything.
"""
import requests
from datetime import datetime, timezone

BRK = "https://bitview.space/api"
MONITOR_JSON = "https://monitor.joeconsorti.com/monitor.json"
TIMEOUT = 30


def _brk_last(name):
    try:
        r = requests.get(f"{BRK}/series/{name}/date/data", params={"from": -1}, timeout=TIMEOUT)
        if r.status_code == 200:
            nums = [x for x in r.json() if isinstance(x, (int, float))]
            return nums[-1] if nums else None
    except Exception:
        pass
    return None


def _brk_series(name, days):
    try:
        r = requests.get(f"{BRK}/series/{name}/date/data", params={"from": -days}, timeout=TIMEOUT)
        if r.status_code == 200:
            return [x if isinstance(x, (int, float)) else None for x in r.json()]
    except Exception:
        pass
    return None


def _pct_change(series, n):
    s = [x for x in (series or []) if isinstance(x, (int, float))]
    if len(s) <= n:
        return None
    return round((s[-1] / s[-1 - n] - 1) * 100, 2)


def _yahoo(sym, rng="6mo"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"
    try:
        r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        res = r.json()["chart"]["result"][0]
        closes = [c for c in res["indicators"]["quote"][0]["close"] if isinstance(c, (int, float))]
        return closes
    except Exception:
        return None


def collect():
    data = {"generated_at": datetime.now(timezone.utc).isoformat()}

    # --- live composite score + levels from the monitor -------------------
    try:
        m = requests.get(MONITOR_JSON, params={"t": datetime.now().timestamp()}, timeout=TIMEOUT).json()
        sc = m.get("score", {})
        data["composite"] = sc.get("composite")
        data["regime"] = sc.get("regime")
        data["verdict"] = sc.get("verdict")
        data["in_bottom_quartile"] = sc.get("in_bottom_quartile")
        data["total_indicators"] = sc.get("total_indicators")
        data["score_history"] = sc.get("history", [])
        data["levels"] = m.get("levels", {})
        data["network_metrics"] = m.get("network_metrics", {})
        data["monitor_watchlist"] = m.get("watchlist", [])
    except Exception as e:
        data["monitor_error"] = str(e)

    # --- on-chain snapshot (BRK) -----------------------------------------
    onchain = {}
    for label, s in {
        "price": "price", "mvrv": "mvrv", "sth_mvrv": "sth_mvrv", "lth_mvrv": "lth_mvrv",
        "nupl": "nupl", "lth_nupl": "lth_nupl", "realized_price": "realized_price",
        "sth_cost_basis": "sth_realized_price", "lth_cost_basis": "lth_realized_price",
        "true_market_mean": "true_market_mean", "ma_350d": "price_sma_350d",
        "reserve_risk": "reserve_risk", "puell": "puell_multiple",
        "sopr": "sopr_24h", "sth_sopr": "sth_sopr_24h", "lth_sopr": "lth_sopr_24h",
        "rhodl": "rhodl_ratio", "hash_rate": "hash_rate",
        "hash_ma_fast": "hash_rate_sma_1m", "hash_ma_slow": "hash_rate_sma_2m",
    }.items():
        onchain[label] = _brk_last(s)

    # 30-day deltas for the movers detector
    deltas = {}
    for label, s in {"price": "price", "mvrv": "mvrv", "sth_mvrv": "sth_mvrv",
                     "puell": "puell_multiple", "lth_sopr": "lth_sopr_24h",
                     "nupl": "nupl", "reserve_risk": "reserve_risk"}.items():
        ser = _brk_series(s, 60)
        deltas[label] = {"d1": _pct_change(ser, 1), "d7": _pct_change(ser, 7),
                         "d30": _pct_change(ser, 30)}
    # derived cohort + profitability reads for the newsletter. 1500-day window
    # (matches the "long lookback" convention already used elsewhere, e.g.
    # render_charts.py's puell/mvrv/hash-ribbons charts) so "lowest ever"
    # style claims can be checked against real history instead of asserted.
    sth_rc = _brk_series("sth_realized_cap", 1500)
    tot_rc = _brk_series("realized_cap", 1500)
    if sth_rc and tot_rc:
        n = min(len(sth_rc), len(tot_rc))
        share = [(a / b * 100) for a, b in zip(sth_rc[-n:], tot_rc[-n:])
                 if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b]
        if share:
            onchain["sth_realized_share"] = round(share[-1], 1)
            deltas["sth_realized_share"] = {"d30": round(share[-1] - share[-30], 2) if len(share) > 30 else None}
            hist_min = min(share)
            onchain["sth_realized_share_hist_min"] = round(hist_min, 1)
            onchain["sth_realized_share_hist_days"] = len(share)
            onchain["sth_realized_share_is_hist_low"] = share[-1] <= hist_min + 1e-9
    sip = _brk_series("supply_in_profit_share", 1500)
    if sip:
        clean = [x for x in sip if isinstance(x, (int, float))]
        if clean:
            onchain["supply_in_profit"] = round(clean[-1], 1)
            deltas["supply_in_profit"] = {"d30": round(clean[-1] - clean[-30], 2) if len(clean) > 30 else None}
            hist_min_sip = min(clean)
            onchain["supply_in_profit_hist_min"] = round(hist_min_sip, 1)
            onchain["supply_in_profit_hist_days"] = len(clean)
    data["onchain"] = onchain
    data["deltas"] = deltas

    # --- macro (Yahoo) ---------------------------------------------------
    macro = {}
    for label, sym in {"gold": "GC=F", "sp500": "^GSPC", "nasdaq": "^IXIC",
                       "move": "^MOVE", "brent": "BZ=F", "copper": "HG=F",
                       "dxy": "DX-Y.NYB", "us10y": "^TNX", "vix": "^VIX",
                       "semis": "SMH"}.items():
        s = _yahoo(sym)
        if s:
            macro[label] = {"price": round(s[-1], 2), "d30": _pct_change(s, 21),
                            "d90": _pct_change(s, 63)}
    data["macro"] = macro

    # --- Fear & Greed ----------------------------------------------------
    try:
        fg = requests.get("https://api.alternative.me/fng/?limit=2", timeout=TIMEOUT).json()["data"]
        data["fear_greed"] = {"value": int(fg[0]["value"]),
                              "label": fg[0]["value_classification"],
                              "yesterday": int(fg[1]["value"])}
    except Exception:
        data["fear_greed"] = None

    return data


if __name__ == "__main__":
    import json
    print(json.dumps(collect(), indent=2, default=str))
