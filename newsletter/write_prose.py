"""
write_prose.py — turns the day's data into Joe-voice narrative.

Uses the Claude API when ANTHROPIC_API_KEY is set. Without a key (or with
--dry-run), it falls back to a clear templated draft so you can preview the
whole newsletter structure and edit the voice/format before going live.

The voice lives entirely in voice_prompt.md — edit that one file to change how
every future issue reads. This module only assembles the request.
"""
import os
import json
import urllib.request
import urllib.error

MODEL = "claude-sonnet-5"          # fast + cheap for daily prose; swap freely
VOICE_FILE = os.path.join(os.path.dirname(__file__), "voice_prompt.md")


def _load_voice():
    try:
        with open(VOICE_FILE) as f:
            return f.read()
    except Exception:
        return "Write in a terse, direct Bitcoin-macro voice. No em-dashes."


def _facts_block(data, selected):
    """Compact, model-friendly digest of the day's numbers."""
    oc = data.get("onchain", {})
    mac = data.get("macro", {})
    fg = data.get("fear_greed") or {}
    lines = [
        f"Composite cycle score: {data.get('composite')} / 100 ({data.get('regime')}, {data.get('verdict')})",
        f"Indicators in bottom quartile: {data.get('in_bottom_quartile')} of {data.get('total_indicators')}",
        f"BTC price: ${oc.get('price'):,.0f}" if oc.get('price') else "BTC price: n/a",
        f"STH cost basis: ${oc.get('sth_cost_basis'):,.0f}" if oc.get('sth_cost_basis') else "",
        f"LTH cost basis: ${oc.get('lth_cost_basis'):,.0f}" if oc.get('lth_cost_basis') else "",
        f"Realized price: ${oc.get('realized_price'):,.0f}" if oc.get('realized_price') else "",
        f"True market mean: ${oc.get('true_market_mean'):,.0f}" if oc.get('true_market_mean') else "",
        f"STH MVRV: {oc.get('sth_mvrv')}", f"LTH SOPR: {oc.get('lth_sopr')}",
        f"Puell: {oc.get('puell')}", f"MVRV: {oc.get('mvrv')}", f"NUPL: {oc.get('nupl')}",
        f"Fear & Greed: {fg.get('value')} ({fg.get('label')}), yesterday {fg.get('yesterday')}",
    ]
    for k, lbl in [("gold", "Gold"), ("sp500", "S&P 500"), ("nasdaq", "Nasdaq"),
                   ("move", "MOVE index"), ("brent", "Brent"), ("copper", "Copper"),
                   ("dxy", "DXY"), ("us10y", "US 10Y"), ("vix", "VIX"), ("semis", "Semis SMH")]:
        m = mac.get(k)
        if m:
            lines.append(f"{lbl}: {m['price']} (30d {m.get('d30')}%, 90d {m.get('d90')}%)")
    lines.append("Charts selected for today: " + ", ".join(s["label"] for s in selected))
    return "\n".join([x for x in lines if x])


def _call_claude(api_key, system, user):
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({
            "model": MODEL, "max_tokens": 2000, "system": system,
            "messages": [{"role": "user", "content": user}],
        }).encode(),
        headers={"content-type": "application/json", "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            raw = r.read()
            print(f"  [diag] Claude status: {r.status}  body ({len(raw)} bytes): {raw[:2000]!r}")
            body = json.loads(raw)
    except urllib.error.HTTPError as e:
        err_body = e.read()
        print(f"  [diag] Claude error: HTTP {e.code} {e.reason}")
        print(f"  [diag] Claude error headers: {dict(e.headers)}")
        print(f"  [diag] Claude error body ({len(err_body)} bytes): {err_body[:2000]!r}")
        raise
    return "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")


def write(data, selected, dry_run=False):
    """Return a dict of newsletter sections. Live via Claude API, or a clear
    templated draft in dry-run / no-key mode."""
    voice = _load_voice()
    facts = _facts_block(data, selected)
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if dry_run or not api_key:
        return _template_fallback(data, selected, facts)

    system = (voice + "\n\nReturn ONLY valid JSON with keys: headline, tldr, "
              "chart_reads (object keyed by the chart label, each a 2-3 paragraph string), "
              "what_to_watch, takeaway. No markdown, no preamble.")
    user = (f"Today's data:\n{facts}\n\nWrite the morning brief. chart_reads must include "
            f"one entry for each of these labels: {[s['label'] for s in selected]}.")
    try:
        raw = _call_claude(api_key, system, user).strip()
        if raw.startswith("```"):
            raw = raw.strip("`").split("\n", 1)[1] if "\n" in raw else raw
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        print(f"  ! Claude API failed ({e}); using template fallback")
        return _template_fallback(data, selected, facts)


def _template_fallback(data, selected, facts):
    """Deterministic, editable draft. Real voice comes from the API in prod,
    but this proves the pipeline end-to-end with zero keys."""
    oc = data.get("onchain", {})
    price = oc.get("price")
    comp = data.get("composite")
    regime = data.get("regime", "")
    verdict = data.get("verdict", "")
    reads = {}
    human = {
        "price_vs_levels": "Price against what holders actually paid. The whole game is where we sit relative to cost basis.",
        "sth_mvrv": "Short-term holders as a group. Below 1.0 means recent buyers are underwater.",
        "lth_sopr": "Whether long-term holders are spending at a profit or a loss. Below 1.0 is a bottom tell.",
        "puell": "Miner revenue stress. Under 1.0 has marked the low of every cycle.",
        "mvrv": "Price versus the network's average cost basis. Low is deep value.",
        "fear_greed": "Crowd sentiment in one number. Extreme fear is where entries are made.",
        "gold": "Hard money's bid. When gold runs, the debasement thesis is live.",
        "yields": "The Fed and the rate regime, read through the 10-year.",
        "move": "Bond-market volatility. Rising stress shows up here first.",
        "semis": "The AI trade versus Bitcoin. A breakdown in semis can rotate capital toward BTC.",
        "btc_gold": "Bitcoin priced in gold. Tells you if BTC is leading or lagging hard money.",
        "sth_share": "The share of network value in coins that moved recently. Falling to multi-year lows means supply has aged into strong hands.",
        "supply_in_profit": "The share of coins worth more than they last moved at. Under 60% is where weak hands finish selling.",
    }
    for s in selected:
        reads[s["label"]] = human.get(s["key"], "Key read for today.") + \
            "  [Live prose is written by Claude here in production.]"
    return {
        "headline": (f"Bitcoin at ${price:,.0f}. The cycle score reads {comp}, {regime}."
                     if price else f"The cycle score reads {comp}, {regime}."),
        "tldr": (f"The monitor sits at {comp} out of 100, {regime.lower()}. The signal is "
                 f"{verdict.lower()}. Charts below carry the detail. "
                 f"[Live TL;DR written by Claude in production.]"),
        "chart_reads": reads,
        "what_to_watch": ("The accumulation zone stays $49.5K to $55K. "
                          "[Live 'what to watch' written by Claude in production.]"),
        "takeaway": (f"The framework reads {verdict.lower()}. "
                     f"[Live takeaway written by Claude in production.]"),
        "_dry_run": True,
        "_facts": facts,
    }
