"""
write_prose.py — turns the day's data into Joe-voice narrative.

Uses the Claude API when ANTHROPIC_API_KEY is set. Without a key (or with
--dry-run), it falls back to a clear templated draft so you can preview the
whole newsletter structure and edit the voice/format before going live.

The voice lives entirely in voice_prompt.md — edit that one file to change how
every future issue reads. This module only assembles the request.
"""
import os
import re
import json
import urllib.request

from chart_select import MACRO_LABELS

MODEL = "claude-opus-5"            # best quality for daily prose; swap freely
FALLBACK_MODEL = "claude-sonnet-5"  # retried once if Opus fails or returns bad output
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


def _sth_share_fact(oc):
    """STH Realized-Cap Share: the share of network value held in recently-
    active/short-term-holder coins -- i.e. how much sellable supply is still
    in active hands. Low = seller exhaustion. Includes the real historical
    floor and window size so the model can't overclaim "lowest ever" beyond
    what the data actually shows."""
    v = oc.get("sth_realized_share")
    if v is None:
        return ""
    hist_min = oc.get("sth_realized_share_hist_min")
    days = oc.get("sth_realized_share_hist_days")
    years = round(days / 365, 1) if days else None
    if oc.get("sth_realized_share_is_hist_low"):
        return (f"STH Realized-Cap Share (active/recent-seller supply -- 'seller exhaustion'): "
                f"{v}%, the LOWEST reading in the last {days} days (~{years} years) of available "
                f"history. Sellers have not been this exhausted in that entire window.")
    return (f"STH Realized-Cap Share (active/recent-seller supply -- 'seller exhaustion'): {v}% "
            f"(the floor over the last {days} days / ~{years} years was {hist_min}%, so today is "
            f"NOT a record low -- do not claim it is, describe it as near multi-year lows instead)")


def _sip_fact(oc):
    v = oc.get("supply_in_profit")
    if v is None:
        return ""
    hist_min = oc.get("supply_in_profit_hist_min")
    return f"Supply in Profit: {v}%" + (f" (floor over available history: {hist_min}%)" if hist_min is not None else "")


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
        _sth_share_fact(oc), _sip_fact(oc),
    ]
    for k, lbl in [("gold", "Gold"), ("sp500", "S&P 500"), ("nasdaq", "Nasdaq"),
                   ("move", "MOVE index"), ("brent", "Brent"), ("copper", "Copper"),
                   ("dxy", "DXY"), ("us10y", "US 10Y"), ("vix", "VIX"), ("semis", "Semis SMH")]:
        m = mac.get(k)
        if m:
            lines.append(f"{lbl}: {m['price']} (30d {m.get('d30')}%, 90d {m.get('d90')}%)")
    lines.append("Charts selected for today: " + ", ".join(s["label"] for s in selected))
    return "\n".join([x for x in lines if x])


def _call_claude(api_key, system, user, model=MODEL):
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({
            "model": model, "max_tokens": 8192, "system": system,
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


def _recent_angles_block(recent_angles):
    """Render the last several days' headlines/lead topics as a system-prompt
    block instructing the model to avoid repeating them. Returns "" if there's
    no history yet."""
    if not recent_angles:
        return ""
    lines = [f"- {e.get('date','?')}: \"{e.get('headline','')}\" (lead topic: {e.get('lead_label','?')})"
             for e in recent_angles if e.get("headline")]
    if not lines:
        return ""
    return (
        "\n\nRECENT ISSUES (most recent last) -- do not repeat these:\n" + "\n".join(lines) +
        "\n\nToday's headline MUST take a distinctly different angle and distinctly different "
        "wording from every headline above -- not a rephrase, not the same lead topic with new "
        "numbers. If the same lead topic (e.g. gold, or the same on-chain metric) genuinely still "
        "dominates today's data, you may still cover it inside the brief, but do NOT make it "
        "today's headline/hook again -- lead on a different angle from today's data instead "
        "(the macro/Fed picture, on-chain cohorts, miners, cycle timing, cross-asset moves, "
        "whatever is actually most notable today besides the recently-used angle)."
    )


def write(data, selected, dry_run=False, recent_angles=None):
    """Return a dict of newsletter sections. Live via Claude API, or a clear
    templated draft in dry-run / no-key mode. recent_angles (optional): the
    last several days' {date, headline, lead_label} entries from
    recent_angles.py, used to steer away from repeating the same angle."""
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
              "takeaway." + _recent_angles_block(recent_angles))
    user = (f"Today's data:\n{facts}\n\n"
            f"Macro charts selected today (each gets its own paragraph in THE MACRO section): "
            f"{macro_labels or 'none'}\n"
            f"Bitcoin/on-chain charts selected today (each gets its own paragraph in THE PAYOFF "
            f"section): {bitcoin_labels}\n\n"
            f"Write macro_paragraphs with at least {max(len(macro_labels), 2)} paragraphs "
            f"(even with no macro chart selected, still open on the macro backdrop) and "
            f"bitcoin_paragraphs with at least {max(len(bitcoin_labels), 1)} paragraphs.")
    for model in (MODEL, FALLBACK_MODEL):
        try:
            raw = _call_claude(api_key, system, user, model=model).strip()
            parsed = json.loads(raw)
            _validate(parsed)
            return parsed
        except Exception as e:
            print(f"  ! {model} failed ({e})")

    print("  ! both models failed; using template fallback")
    return _template_fallback(data, selected, facts)


# Matches a bare schema/field-name-style token (snake_case, no spaces or
# punctuation) -- catches cases like the model echoing "paragraphs_placeholder"
# instead of writing prose for a field.
_SCHEMA_ARTIFACT = re.compile(r"^[a-z][a-z0-9_]*$")


def _looks_like_prose(text, min_len=15):
    text = (text or "").strip()
    return len(text) >= min_len and not _SCHEMA_ARTIFACT.match(text)


def _validate(parsed):
    for key in ("headline", "tldr", "macro_headline", "bitcoin_headline",
                "watch_macro", "watch_price", "takeaway"):
        if not _looks_like_prose(parsed.get(key)):
            raise ValueError(f"{key} looks like a schema artifact, not prose: {parsed.get(key)!r}")
    for key in ("macro_paragraphs", "bitcoin_paragraphs"):
        paras = parsed.get(key) or []
        if not paras:
            raise ValueError(f"{key} is empty")
        for p in paras:
            if not _looks_like_prose(p):
                raise ValueError(f"{key} contains a schema artifact, not prose: {p!r}")


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
