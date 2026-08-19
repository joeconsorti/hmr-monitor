"""
send_special_issue.py — one-off newsletter issue with a hand-picked angle and
chart lineup, instead of the day's auto-scored/auto-selected story.

Reuses the same voice, model retry chain, validation, chart rendering/hosting,
HTML assembly, and Beehiiv send as build_newsletter.py (including DRAFT_ONLY),
so it's identical infrastructure with a custom prompt and chart list layered
on top for this issue only. The daily automated pipeline is untouched.

  python send_special_issue.py --dry-run     # local HTML preview, no keys needed
  python send_special_issue.py               # live: writes prose (Claude) + sends (Beehiiv)
"""
import os
import sys
import json

import collect_data
import chart_select as selector
import render_charts
import publish_charts
import write_prose
import assemble_html
import build_newsletter
import recent_angles

OUTDIR = os.path.join(os.path.dirname(__file__), "out")

# This issue's angle: supply-side seller exhaustion -- the share of Bitcoin
# held by recently-active/short-term sellers has fallen to (or near) the
# lowest level in the available data. Charts are hand-picked to prove that
# claim with real on-chain data rather than auto-scored.
SELECTED = [
    {"key": "price_vs_levels", "label": "price_vs_levels"},
    {"key": "sth_share", "label": "sth_share"},
    {"key": "supply_in_profit", "label": "supply_in_profit"},
    {"key": "mvrv", "label": "mvrv"},
]

SPECIAL_SCHEMA = dict(write_prose.RESPONSE_SCHEMA)
SPECIAL_SCHEMA["properties"] = dict(write_prose.RESPONSE_SCHEMA["properties"])
SPECIAL_SCHEMA["properties"]["video_cta"] = {"type": "string"}
# video_cta stays optional -- this issue has no video tie-in, unlike the
# miners/AI issue this script was originally written for.

SPECIAL_ANGLE = """
Today's issue has a specific angle, different from a normal auto-generated day.
Do not write the usual data-of-the-day story. Instead build the whole issue
around this narrative:

1. Supply-side seller exhaustion. STH Realized-Cap Share -- the share of
   Bitcoin's realized value held by recently-active, short-term-holder coins
   -- measures how much sellable supply is still in active hands. The data
   below tells you the exact current reading AND the real historical floor
   over the available lookback window, plus whether today IS or IS NOT that
   record low. Use those exact numbers. If today genuinely is the record low
   for that window, say plainly that sellers have not been this exhausted in
   that entire stretch of history -- that is a strong, real claim, no need to
   inflate it further. If today is NOT the record low, do not claim it is;
   describe it honestly as a multi-year low instead. Precision beats punch.
2. Corroborate with Supply in Profit: a falling share of coins able to sell
   at a profit reinforces the same seller-exhaustion read from a different
   angle. State the real number given below.
3. Cross-check against MVRV (price vs. network cost basis) as the standard
   valuation read, stated honestly against its real reading -- don't force
   it to agree if the number doesn't support the same conclusion.
4. Structure: THE MACRO section opens on the felt tension -- most people
   assume a market this beaten-down still has plenty of sellers left in it,
   and that assumption is what today's data actually contradicts -- then
   pivots into the supply mechanics as the setup. There is no dedicated
   macro chart selected today; that's fine, still write real macro_paragraphs
   per the usual structure, just without an inline chart image in that
   section. THE PAYOFF section carries the on-chain proof: STH Realized-Cap
   Share as the headline data point, then Supply in Profit and MVRV as
   corroboration, one paragraph each.
5. No video CTA today. Leave video_cta out entirely.
"""


def main():
    dry = "--dry-run" in sys.argv
    os.makedirs(OUTDIR, exist_ok=True)

    print("1/6 collecting data...")
    data = collect_data.collect()

    print("2/6 charts (hand-picked for this issue)...")
    print(f"     charts: {[s['label'] for s in SELECTED]}")

    print("3/6 rendering charts...")
    charts = render_charts.render(SELECTED, data, OUTDIR)

    print("4/6 publishing charts...")
    charts = publish_charts.publish(charts, dry_run=dry)

    print("5/6 writing prose...")
    prose = write_special_prose(data, dry_run=dry)

    if not dry and prose.get("headline"):
        recent_angles.record(prose["headline"], "special:" + SELECTED[0]["label"],
                             chart_labels=[s["label"] for s in SELECTED])

    print("6/6 assembling HTML...")
    html = assemble_html.assemble(prose, charts, data, inline_base64=dry)
    preview_path = os.path.join(OUTDIR, "special_preview.html")
    with open(preview_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"     preview: {preview_path}")

    subject = prose.get("headline", "The Bitcoin Brief")

    print("7/7 sending...")
    if dry:
        print("     DRY RUN — not sending. Open the preview to review.")
    else:
        draft_only = os.environ.get("DRAFT_ONLY", "").strip() in ("1", "true", "yes", "on")
        if draft_only:
            print("     DRAFT_ONLY is on — landing as a Beehiiv draft, NOT emailing the list.")
        build_newsletter.send_beehiiv(html, subject, as_draft=draft_only)

    print("done.")
    return preview_path


def write_special_prose(data, dry_run=False):
    voice = write_prose._load_voice()
    facts = write_prose._facts_block(data, SELECTED)
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if dry_run or not api_key:
        return _template_fallback(data, facts)

    macro_labels = [s["label"] for s in SELECTED if s["label"] in write_prose.MACRO_LABELS]
    bitcoin_labels = [s["label"] for s in SELECTED if s["label"] not in write_prose.MACRO_LABELS]

    recent = recent_angles.load_recent()
    system = voice + "\n\n" + SPECIAL_ANGLE + write_prose._recent_angles_block(recent)
    user = (f"Today's data:\n{facts}\n\n"
            f"Macro charts selected today: {macro_labels or 'none'}\n"
            f"Bitcoin/on-chain charts selected today: {bitcoin_labels}\n\n"
            f"Write macro_paragraphs and bitcoin_paragraphs covering the angle above, "
            f"roughly one paragraph per selected chart in each section.")

    for model in (write_prose.MODEL, write_prose.FALLBACK_MODEL):
        try:
            raw = _call_claude_special(api_key, system, user, model=model).strip()
            parsed = json.loads(raw)
            write_prose._validate(parsed)
            if parsed.get("video_cta") and not write_prose._looks_like_prose(parsed.get("video_cta")):
                raise ValueError(f"video_cta looks like a schema artifact: {parsed.get('video_cta')!r}")
            return parsed
        except Exception as e:
            print(f"  ! {model} failed ({e})")

    print("  ! both models failed; using template fallback")
    return _template_fallback(data, facts)


def _call_claude_special(api_key, system, user, model):
    import urllib.request
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({
            "model": model, "max_tokens": 8192, "system": system,
            "thinking": {"type": "disabled"},
            "output_config": {"format": {"type": "json_schema", "schema": SPECIAL_SCHEMA}},
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


def _template_fallback(data, facts):
    base = write_prose._template_fallback(data, SELECTED, facts)
    base["headline"] = "Sellers Have Nothing Left To Sell"
    return base


if __name__ == "__main__":
    main()
