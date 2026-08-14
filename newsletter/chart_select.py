"""
select.py — decides which charts lead the newsletter each morning.

This is the "automatically determine the relevant charts for the day" engine.
It scores every candidate chart by how much it moved and how meaningful its
current reading is, then returns the top N. Edit the RULES table to change what
triggers a chart to lead. Each rule is a small function of the day's data that
returns a priority score (higher = more newsletter-worthy).

Also flags BIG NEWS days (composite regime shift, large price move, extreme
readings), which the builder uses to switch from auto-send to draft.
"""

# The always-eligible core. price_vs_levels always leads (it's the anchor).
# Everything else competes for the remaining slots by score.

def _abs(x):
    return abs(x) if isinstance(x, (int, float)) else 0


def score_price_vs_levels(d):
    # Always the lead chart. Huge base score.
    return 1000


def score_sth_mvrv(d):
    v = d.get("onchain", {}).get("sth_mvrv")
    move = _abs(d.get("deltas", {}).get("sth_mvrv", {}).get("d7"))
    s = move * 2
    if v is not None and v < 1.0:      # underwater = notable
        s += 40
    return s


def score_lth_sopr(d):
    v = d.get("onchain", {}).get("lth_sopr")
    move = _abs(d.get("deltas", {}).get("lth_sopr", {}).get("d7"))
    s = move * 3
    if v is not None and v < 1.0:      # LTHs at a loss = strong signal
        s += 50
    return s


def score_puell(d):
    v = d.get("onchain", {}).get("puell")
    move = _abs(d.get("deltas", {}).get("puell", {}).get("d7"))
    s = move * 2
    if v is not None and v < 1.0:      # miner stress bottom zone
        s += 35
    return s


def score_mvrv(d):
    v = d.get("onchain", {}).get("mvrv")
    move = _abs(d.get("deltas", {}).get("mvrv", {}).get("d7"))
    s = move * 2
    if v is not None and (v < 1.2 or v > 3.0):
        s += 30
    return s


def score_fear_greed(d):
    fg = d.get("fear_greed")
    if not fg:
        return 0
    move = _abs(fg["value"] - fg["yesterday"])
    s = move * 1.5
    if fg["value"] <= 25 or fg["value"] >= 75:   # extreme
        s += 30
    return s


def score_gold(d):
    g = d.get("macro", {}).get("gold", {})
    return _abs(g.get("d30")) * 3        # debasement thesis chart


def score_btc_gold(d):
    # BTC/gold ratio matters when the two diverge
    g = d.get("macro", {}).get("gold", {})
    p = d.get("deltas", {}).get("price", {})
    return _abs((p.get("d30") or 0) - (g.get("d30") or 0)) * 1.5


def score_yields(d):
    y = d.get("macro", {}).get("us10y", {})
    return _abs(y.get("d30")) * 2.5      # Fed/rate regime


def score_move(d):
    m = d.get("macro", {}).get("move", {})
    return _abs(m.get("d30")) * 1.5      # bond vol / stress


def score_semis_rotation(d):
    s = d.get("macro", {}).get("semis", {})
    return _abs(s.get("d30")) * 1.2      # AI-trade rotation watch


def score_sth_share(d):
    v = d.get("onchain", {}).get("sth_realized_share")
    move = _abs(d.get("deltas", {}).get("sth_realized_share", {}).get("d30"))
    s = move * 3
    if v is not None and v < 25:      # multi-year-low territory = strong signal
        s += 45
    return s


def score_supply_in_profit(d):
    v = d.get("onchain", {}).get("supply_in_profit")
    move = _abs(d.get("deltas", {}).get("supply_in_profit", {}).get("d30"))
    s = move * 2
    if v is not None and v < 60:      # stress zone
        s += 35
    return s


# label -> (scoring function, chart-builder key used by render_charts.py)
RULES = {
    "price_vs_levels": (score_price_vs_levels, "price_vs_levels"),
    "sth_mvrv":        (score_sth_mvrv, "sth_mvrv"),
    "lth_sopr":        (score_lth_sopr, "lth_sopr"),
    "puell":           (score_puell, "puell"),
    "mvrv":            (score_mvrv, "mvrv"),
    "sth_share":       (score_sth_share, "sth_share"),
    "supply_in_profit": (score_supply_in_profit, "supply_in_profit"),
    "fear_greed":      (score_fear_greed, "fear_greed"),
    "gold":            (score_gold, "gold"),
    "btc_gold":        (score_btc_gold, "btc_gold"),
    "yields":          (score_yields, "yields"),
    "move":            (score_move, "move"),
    "semis":           (score_semis_rotation, "semis"),
}


def select_charts(data, n_weekday=4, n_weekend=2, is_weekend=False):
    """Return the top charts for the day as a ranked list of
    {key, label, score}. price_vs_levels always leads."""
    n = n_weekend if is_weekend else n_weekday
    scored = []
    for label, (fn, chart_key) in RULES.items():
        try:
            s = fn(data)
        except Exception:
            s = 0
        scored.append({"label": label, "key": chart_key, "score": round(s, 1)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:n]


def detect_big_news(data):
    """Return (is_big_news, reasons[]). Big-news days land as a Beehiiv draft
    for a human glance instead of auto-sending. Tune thresholds freely."""
    reasons = []
    # large 1-day price move
    d1 = data.get("deltas", {}).get("price", {}).get("d1")
    if isinstance(d1, (int, float)) and abs(d1) >= 5:
        reasons.append(f"BTC moved {d1:+.1f}% in a day")
    # regime near a band edge (possible flip)
    comp = data.get("composite")
    if isinstance(comp, (int, float)):
        for edge in (15, 35, 65, 85):
            if abs(comp - edge) <= 1:
                reasons.append(f"composite {comp} sitting on the {edge} band edge")
    # extreme fear/greed
    fg = data.get("fear_greed")
    if fg and (fg["value"] <= 10 or fg["value"] >= 90):
        reasons.append(f"Fear & Greed at an extreme ({fg['value']})")
    # big macro vol spike
    move = data.get("macro", {}).get("move", {}).get("d30")
    if isinstance(move, (int, float)) and abs(move) >= 20:
        reasons.append(f"bond volatility (MOVE) {move:+.0f}% in 30 days")
    return (len(reasons) > 0, reasons)
