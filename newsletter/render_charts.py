"""
render_charts.py — renders the selected charts as HMR-branded PNGs.
Same visual language as the monitor and the live-call chart packs.
Each builder returns a saved file path. Add a new builder + a RULES entry in
select.py to introduce a new chart type.
"""
import os
import hashlib
from datetime import datetime
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter

ORANGE = "#FD6F0B"; BG = "#0d1117"; PANEL = "#131a22"; GRID = "#1c2530"
TXT = "#e6edf3"; MUT = "#9aa4b0"; TEAL = "#2dd4bf"; RED = "#e2504a"
plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
    "text.color": TXT, "axes.labelcolor": MUT, "xtick.color": MUT, "ytick.color": MUT,
    "axes.edgecolor": GRID, "grid.color": GRID, "font.size": 11, "font.family": "DejaVu Sans",
})
BRK = "https://bitview.space/api"


def _style(ax):
    ax.grid(True, alpha=.25, lw=.6)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)


def _brk(name, days=1500):
    try:
        r = requests.get(f"{BRK}/series/{name}/date/data", params={"from": -days}, timeout=30)
        if r.status_code == 200:
            return [x if isinstance(x, (int, float)) else None for x in r.json()]
    except Exception:
        pass
    return None


def _dates(days=1500):
    try:
        r = requests.get(f"{BRK}/series/date/date/data", params={"from": -days}, timeout=30)
        if r.status_code == 200:
            return [datetime.strptime(d, "%Y-%m-%d") for d in r.json()]
    except Exception:
        pass
    return None


def _yahoo(sym, rng="1y"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"}).json()["chart"]["result"][0]
    ts = [datetime.fromtimestamp(t) for t in r["timestamp"]]
    c = r["indicators"]["quote"][0]["close"]
    return [(t, v) for t, v in zip(ts, c) if v is not None]


def _align(vals, D):
    if not vals or not D:
        return [], []
    n = min(len(vals), len(D))
    xs, ys = [], []
    for x, y in zip(D[-n:], vals[-n:]):
        if y is not None:
            xs.append(x); ys.append(y)
    return xs, ys


def _save(fig, outdir, name):
    path = os.path.join(outdir, name)
    fig.tight_layout(); fig.savefig(path, dpi=130, bbox_inches="tight"); plt.close(fig)
    return _versioned(path)


def _versioned(path):
    """Rename to a content-hashed filename (name.<hash>.png). Plain, repeated
    filenames like "gold.png" meant a same-day re-run -- a manual retry, or a
    second pipeline like send_special_issue.py sharing the same date folder
    -- would silently overwrite the exact file an already-generated/already-
    sent issue was pointing at, so a reader could see chart pixels from a
    different run than the one whose numbers are in the prose. Hashing the
    content into the filename gives every run's image its own permanent URL:
    nothing ever overwrites, and a CDN/browser cache can never go stale since
    new content always means a new URL."""
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()[:10]
    root, ext = os.path.splitext(path)
    versioned = f"{root}.{digest}{ext}"
    os.replace(path, versioned)
    return versioned


# ---- individual chart builders -----------------------------------------
def build_price_vs_levels(data, outdir):
    D = _dates(1200)
    px, py = _align(_brk("price", 1200), D)
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(px, py, color=TXT, lw=2, zorder=5, label="BTC Price")
    for s, c, lab in [("lth_realized_price", RED, "LTH Cost Basis"),
                      ("realized_price", "#9aa4b0", "Realized Price"),
                      ("true_market_mean", "#5aa9e6", "True Market Mean"),
                      ("price_sma_350d", TEAL, "350D MA")]:
        x, y = _align(_brk(s, 1200), D)
        if x:
            ax.plot(x, y, color=c, lw=1.2, alpha=.9, label=lab)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.set_title("BTC Price vs Cost-Basis Levels", color=TXT, fontsize=13, loc="left", pad=12)
    ax.legend(loc="upper left", fontsize=9, facecolor=PANEL, edgecolor=GRID, labelcolor=TXT)
    _style(ax); return _save(fig, outdir, "price_vs_levels.png")


def _oscillator(series_name, title, threshold, days, outdir, fname, fill_below=True):
    D = _dates(days)
    x, y = _align(_brk(series_name, days), D)
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.plot(x, y, color=ORANGE, lw=1.6)
    ax.axhline(threshold, color=MUT, ls="--", lw=1)
    if fill_below:
        ax.fill_between(x, y, threshold, where=[v < threshold for v in y], color=TEAL, alpha=.18)
    ax.set_title(title, color=TXT, fontsize=13, loc="left", pad=12)
    _style(ax); return _save(fig, outdir, fname)


def build_sth_mvrv(data, outdir):
    return _oscillator("sth_mvrv", "Short-Term Holder MVRV (below 1.0 = tourists underwater)",
                       1.0, 1200, outdir, "sth_mvrv.png")


def build_lth_sopr(data, outdir):
    D = _dates(1200)
    x, y = _align(_brk("lth_sopr_24h", 1200), D)
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.plot(x, y, color=ORANGE, lw=1.4)
    ax.axhline(1.0, color=MUT, ls="--", lw=1)
    ax.fill_between(x, y, 1.0, where=[v < 1.0 for v in y], color=TEAL, alpha=.18)
    ax.set_ylim(0.5, 2.0)     # clip rare spikes so daily detail stays readable
    ax.set_title("Long-Term Holder SOPR (below 1.0 = LTHs selling at a loss)",
                 color=TXT, fontsize=13, loc="left", pad=12)
    _style(ax); return _save(fig, outdir, "lth_sopr.png")


def build_puell(data, outdir):
    return _oscillator("puell_multiple", "Puell Multiple (below 1.0 marks every cycle bottom)",
                       1.0, 1500, outdir, "puell.png")


def build_mvrv(data, outdir):
    return _oscillator("mvrv", "MVRV Ratio (deep value near 1.0, tops cluster above 3.0)",
                       1.0, 1500, outdir, "mvrv.png")


def build_gold(data, outdir):
    s = _yahoo("GC=F", "1y")
    x = [t for t, v in s]; y = [v for t, v in s]
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.plot(x, y, color="#e0b83a", lw=1.8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.set_title("Gold (the debasement bid)", color=TXT, fontsize=13, loc="left", pad=12)
    _style(ax); return _save(fig, outdir, "gold.png")


def build_yields(data, outdir):
    s = _yahoo("^TNX", "1y")
    x = [t for t, v in s]; y = [v for t, v in s]
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.plot(x, y, color="#5aa9e6", lw=1.6)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax.set_title("US 10-Year Yield (the Fed / rate regime)", color=TXT, fontsize=13, loc="left", pad=12)
    _style(ax); return _save(fig, outdir, "yields.png")


def build_move(data, outdir):
    s = _yahoo("^MOVE", "1y")
    x = [t for t, v in s]; y = [v for t, v in s]
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.plot(x, y, color="#c08bd4", lw=1.6)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax.set_title("MOVE Index (bond-market volatility)", color=TXT, fontsize=13, loc="left", pad=12)
    _style(ax); return _save(fig, outdir, "move.png")


def build_semis(data, outdir):
    n = _yahoo("^IXIC", "3mo"); s = _yahoo("SMH", "3mo"); b = _yahoo("BTC-USD", "3mo")
    def norm(series):
        base = series[0][1]
        return [t for t, v in series], [v / base * 100 for t, v in series]
    fig, ax = plt.subplots(figsize=(11, 4.8))
    for series, c, lab in [(n, "#5aa9e6", "Nasdaq"), (s, "#e0873a", "Semis (SMH)"), (b, ORANGE, "Bitcoin")]:
        xs, ys = norm(series); ax.plot(xs, ys, color=c, lw=1.8, label=lab)
    ax.axhline(100, color=MUT, ls="--", lw=.8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.set_title("AI Trade vs Bitcoin (rotation watch)", color=TXT, fontsize=13, loc="left", pad=12)
    ax.legend(loc="upper left", fontsize=9, facecolor=PANEL, edgecolor=GRID, labelcolor=TXT)
    _style(ax); return _save(fig, outdir, "semis.png")


def build_btc_gold(data, outdir):
    bx = _yahoo("BTC-USD", "1y"); gx = _yahoo("GC=F", "1y")
    gmap = {d.date(): v for d, v in gx}
    rx, ry = [], []
    for d, v in bx:
        g = gmap.get(d.date())
        if g:
            rx.append(d); ry.append(v / g)
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.plot(rx, ry, color=ORANGE, lw=1.6)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax.set_title("Bitcoin / Gold Ratio", color=TXT, fontsize=13, loc="left", pad=12)
    _style(ax); return _save(fig, outdir, "btc_gold.png")


def build_fear_greed(data, outdir):
    # simple gauge-style bar
    fg = data.get("fear_greed", {}) or {}
    val = fg.get("value", 50)
    fig, ax = plt.subplots(figsize=(11, 2.4))
    ax.barh([0], [100], color=PANEL, height=.5)
    color = TEAL if val <= 45 else (RED if val >= 55 else MUT)
    ax.barh([0], [val], color=color, height=.5)
    ax.axvline(val, color=TXT, lw=2)
    ax.text(val, 0.5, f"{val} · {fg.get('label','')}", color=TXT, fontsize=12, ha="center")
    ax.set_xlim(0, 100); ax.set_ylim(-1, 1); ax.axis("off")
    ax.set_title("Fear & Greed Index", color=TXT, fontsize=13, loc="left", pad=12)
    return _save(fig, outdir, "fear_greed.png")


def build_sth_share(data, outdir):
    D = _dates(1500)
    num = _brk("sth_realized_cap", 1500)
    den = _brk("realized_cap", 1500)
    if not num or not den:
        raise RuntimeError("realized cap series unavailable")
    n = min(len(num), len(den), len(D) if D else 10**9)
    share = [(a / b * 100 if (isinstance(a, (int, float)) and isinstance(b, (int, float)) and b) else None)
             for a, b in zip(num[-n:], den[-n:])]
    x, y = _align(share, D)
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.plot(x, y, color="#e0873a", lw=1.6)
    if y:
        ax.axhline(y[-1], color=MUT, ls=":", lw=.8)
    ax.set_title("Short-Term Holder Realized-Cap Share (supply aging into strong hands)",
                 color=TXT, fontsize=13, loc="left", pad=12)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    _style(ax); return _save(fig, outdir, "sth_share.png")


def build_supply_in_profit(data, outdir):
    return _oscillator("supply_in_profit_share",
                       "Supply in Profit (below 60% is where weak hands finish selling)",
                       60.0, 1500, outdir, "supply_in_profit.png", fill_below=True)


def build_hash_ribbons(data, outdir):
    """Hash ribbons: 30D vs 60D hashrate moving averages. Fast below slow
    marks miner capitulation. Every historical instance (not just the latest)
    gets shaded and annotated so the reader sees the recurring pattern."""
    D = _dates(1500)
    fast = _brk("hash_rate_sma_1m", 1500)
    slow = _brk("hash_rate_sma_2m", 1500)
    if not fast or not slow or not D:
        raise RuntimeError("hash rate ribbon series unavailable")
    n = min(len(D), len(fast), len(slow))
    scale = 1e18   # H/s -> EH/s
    dates = D[-n:]
    f = [x / scale if isinstance(x, (int, float)) else None for x in fast[-n:]]
    s = [x / scale if isinstance(x, (int, float)) else None for x in slow[-n:]]

    runs, in_run, start = [], False, None
    for i in range(n):
        below = f[i] is not None and s[i] is not None and f[i] < s[i]
        if below and not in_run:
            in_run, start = True, i
        elif not below and in_run:
            in_run = False
            runs.append((start, i - 1))
    if in_run:
        runs.append((start, n - 1))
    runs = [r for r in runs if r[1] - r[0] >= 2]   # drop single-day noise

    fig, ax = plt.subplots(figsize=(11, 5.2))
    ax.plot(dates, f, color=ORANGE, lw=1.6, label="30D Hashrate MA (fast)")
    ax.plot(dates, s, color="#5aa9e6", lw=1.6, label="60D Hashrate MA (slow)")
    ax.margins(y=0.12)   # headroom so capitulation labels near the data max don't clip
    ylim_top = ax.get_ylim()[1]
    for a, b in runs:
        ax.axvspan(dates[a], dates[b], color=TEAL, alpha=.18)
        window = [v for v in f[a:b + 1] + s[a:b + 1] if v is not None]
        if window:
            label_y = min(max(window) * 1.02, ylim_top * 0.99)
            ax.annotate("Capitulation", xy=(dates[(a + b) // 2], label_y),
                        color=TEAL, fontsize=8.5, ha="center")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax.set_title("Hash Ribbons (miner capitulation: fast MA below slow MA)",
                 color=TXT, fontsize=13, loc="left", pad=12)
    ax.legend(loc="upper left", fontsize=9, facecolor=PANEL, edgecolor=GRID, labelcolor=TXT)
    _style(ax); return _save(fig, outdir, "hash_ribbons.png")


BUILDERS = {
    "price_vs_levels": build_price_vs_levels,
    "sth_mvrv": build_sth_mvrv,
    "lth_sopr": build_lth_sopr,
    "puell": build_puell,
    "mvrv": build_mvrv,
    "gold": build_gold,
    "yields": build_yields,
    "move": build_move,
    "semis": build_semis,
    "btc_gold": build_btc_gold,
    "fear_greed": build_fear_greed,
    "sth_share": build_sth_share,
    "supply_in_profit": build_supply_in_profit,
    "hash_ribbons": build_hash_ribbons,
}


def render(selected, data, outdir):
    """Render each selected chart. Returns list of
    {key, label, path} for the ones that built successfully."""
    os.makedirs(outdir, exist_ok=True)
    out = []
    for item in selected:
        fn = BUILDERS.get(item["key"])
        if not fn:
            continue
        try:
            path = fn(data, outdir)
            out.append({"key": item["key"], "label": item["label"], "path": path})
        except Exception as e:
            print(f"  ! chart {item['key']}: {e}")
    return out
