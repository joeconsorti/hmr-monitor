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

from chart_select import MACRO_LABELS

MODEL = "claude-opus-5"            # best quality for daily prose; swap freely
VOICE_FILE = os.path.join(os.path.dirname(__file__), "voice_prompt.md")

# Structured outputs schema. The brief opens on THE MACRO (macro_headline +
# macro_paragraphs) and narrows into THE PAYOFF (bitcoin_headline +
# bitcoin_paragraphs) as the causal result -- see voice_prompt.md's STRUCTURE
# section. *_paragraphs are arrays so assemble_html.py can interleave a chart
# image after each one without re-splitting a block of text.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "tldr": {"type": "string"},
        "macro_headline": {"type": "string"},
        "macro_paragraphs": {"type": "array", "items": {"type": "string"}},
        "bitcoin_headline": {"type": "string"},
        "bitcoin_paragraphs": {"type": "array", "items": {"type": "string"}},
        "watch_macro": {"type": "string"},
        "watch_price": {"type": "string"},
        "takeaway": {"type": "string"},
    },
    "required": ["headline", "tldr", "macro_headline", "macro_paragraphs",
                 "bitcoin_headline", "bitcoin_paragraphs", "watch_macro",
                 "watch_price", "takeaway"],
    "additionalProperties": False,
}


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
            "model": MODEL, "max_tokens": 8192, "system": system,
            "thinking": {"type": "disabled"},
            "output_config": {"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
            "messages": [{"role": "user", "content": user}],
        }).encode(),
        headers={"content-type": "application/json", "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"},
    )
    with urllib.request.urlopen(req, timeout=150) as r:
        body = json.loads(r.read())
    if body.get("stop_reason") == "max_tokens":
        raise RuntimeError("response truncated at max_tokens")
    return "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")


def write(data, selected, dry_run=False):
    """Return a dict of newsletter sections. Live via Claude API, or a clear
    templated draft in dry-run / no-key mode."""
    voice = _load_voice()
    facts = _facts_block(data, selected)
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if dry_run or not api_key:
        return _template_fallback(data, selected, facts)

    macro_labels = [s["label"] for s in selected if s["label"] in MACRO_LABELS]
    bitcoin_labels = [s["label"] for s in selected if s["label"] not in MACRO_LABELS]

    system = (voice + "\n\nWrite the daily Bitcoin newsletter content, macro-first: a headline, "
              "a tldr, THE MACRO section (macro_headline + macro_paragraphs), THE PAYOFF section "
              "(bitcoin_headline + bitcoin_paragraphs) that resolves the macro story into Bitcoin "
              "as its causal payoff, what to watch (a macro catalyst, then a price level), and a "
              "takeaway.")
    user = (f"Today's data:\n{facts}\n\n"
            f"Macro charts selected today (each gets its own paragraph in THE MACRO section): "
            f"{macro_labels or 'none'}\n"
            f"Bitcoin/on-chain charts selected today (each gets its own paragraph in THE PAYOFF "
            f"section): {bitcoin_labels}\n\n"
            f"Write macro_paragraphs with at least {max(len(macro_labels), 2)} paragraphs "
            f"(even with no macro chart selected, still open on the macro backdrop) and "
            f"bitcoin_paragraphs with at least {max(len(bitcoin_labels), 1)} paragraphs.")
    try:
        raw = _call_claude(api_key, system, user).strip()
        return json.loads(raw)
    except Exception as e:
        print(f"  ! Claude API failed ({e}); using template fallback")
        return _template_fallback(data, selected, facts)


def _template_fallback(data, selected, facts):
    """Deterministic, editable draft. Real voice comes from the API in prod,
    but this proves the pipeline end-to-end with zero keys."""
    comp = data.get("composite")
    regime = data.get("regime", "")
    verdict = data.get("verdict", "")
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
    macro_selected = [s for s in selected if s["label"] in MACRO_LABELS]
    bitcoin_selected = [s for s in selected if s["label"] not in MACRO_LABELS]

    macro_paragraphs = [
        human.get(s["key"], "Key macro read for today.") + "  [Live macro paragraph written by Claude in production.]"
        for s in macro_selected
    ] or ["The macro backdrop sets today's stage. [Live macro paragraph written by Claude in production.]"]

    bitcoin_paragraphs = [
        human.get(s["key"], "Key read for today.") + "  [Live Bitcoin paragraph written by Claude in production.]"
        for s in bitcoin_selected
    ] or ["Bitcoin's on-chain picture follows from the macro above. [Live Bitcoin paragraph written by Claude in production.]"]

    return {
        "headline": "The Setup Nobody's Watching Yet",
        "tldr": (f"The monitor sits at {comp} out of 100, {regime.lower()}. The signal is "
                 f"{verdict.lower()}. The macro and on-chain detail follow below. "
                 f"[Live TL;DR written by Claude in production.]"),
        "macro_headline": "The Macro Backdrop",
        "macro_paragraphs": macro_paragraphs,
        "bitcoin_headline": "Bitcoin's Setup",
        "bitcoin_paragraphs": bitcoin_paragraphs,
        "watch_macro": "The next macro catalyst to watch. [Live 'what to watch' macro line written by Claude in production.]",
        "watch_price": ("The accumulation zone stays $49.5K to $55K. "
                        "[Live 'what to watch' price line written by Claude in production.]"),
        "takeaway": (f"The framework reads {verdict.lower()}. "
                     f"[Live takeaway written by Claude in production.]"),
        "_dry_run": True,
        "_facts": facts,
    }
