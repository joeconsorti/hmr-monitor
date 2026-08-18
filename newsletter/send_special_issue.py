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

OUTDIR = os.path.join(os.path.dirname(__file__), "out")

# This issue's angle: miners diversifying into AI compute is a bullish signal
# for Bitcoin, and two big names have separately flagged that the cycle bottom
# looks close. Charts are hand-picked to back that up rather than auto-scored.
SELECTED = [
    {"key": "hash_ribbons", "label": "hash_ribbons"},
    {"key": "price_vs_levels", "label": "price_vs_levels"},
    {"key": "puell", "label": "puell"},
    {"key": "mvrv", "label": "mvrv"},
]

SPECIAL_SCHEMA = dict(write_prose.RESPONSE_SCHEMA)
SPECIAL_SCHEMA["properties"] = dict(write_prose.RESPONSE_SCHEMA["properties"])
SPECIAL_SCHEMA["properties"]["video_cta"] = {"type": "string"}
SPECIAL_SCHEMA["required"] = write_prose.RESPONSE_SCHEMA["required"] + ["video_cta"]

SPECIAL_ANGLE = """
Today's issue has a specific angle, different from a normal auto-generated day.
Do not write the usual data-of-the-day story. Instead build the whole issue
around this narrative:

1. Bitcoin miners are increasingly pivoting excess capacity into AI/HPC
   compute hosting. Frame this as bullish for Bitcoin: it diversifies miner
   revenue away from pure block-subsidy dependence, reduces the forced,
   panic-driven coin selling that miners have historically done to cover
   costs during stress, and signals miners have enough confidence in
   Bitcoin's long game to invest in infrastructure rather than exit.
2. BlackRock has publicly said it sees the Bitcoin cycle bottom as close.
3. VanEck has publicly said a number of Bitcoin bottom indicators are
   already firing.
4. Use the hash ribbons chart (fast 30D hashrate MA vs slow 60D MA) as the
   on-chain confirmation: it's annotated with every prior instance of minor
   miner capitulation (fast dipping below slow), not just the latest one, so
   ground the read in that historical pattern, not just today's snapshot.
   Tie the miner-AI-pivot point directly to what the ribbons show.
5. Use Puell Multiple (miner revenue stress vs history) and MVRV (price vs
   network cost basis) as the supporting on-chain reads. State plainly, using
   the real numbers given below, whether they're actually in bottom-signal
   territory right now or not yet there. VanEck's "indicators are firing"
   claim only lands if it's checked against real data, not just repeated.
6. Structure: THE MACRO section carries the institutional angle (miners
   pivoting to AI, BlackRock, VanEck) as the macro-scale story: big money and
   infrastructure builders positioning early. THE PAYOFF section carries the
   on-chain confirmation (hash ribbons, Puell, MVRV) as Bitcoin's own data
   either backing that up or showing where it's not fully there yet.
7. Close with a video_cta field: one or two sentences telling the reader to
   turn on notifications for tonight's YouTube video, which goes deeper on
   all of this. Make it feel like a natural next step, not a bolted-on ask.
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

    system = voice + "\n\n" + SPECIAL_ANGLE
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
            if not write_prose._looks_like_prose(parsed.get("video_cta")):
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
    base["headline"] = "The Miners Are Telling You Something"
    base["video_cta"] = ("[Live video CTA written by Claude in production.] "
                         "Turn on notifications, tonight's YouTube video goes deeper on this.")
    return base


if __name__ == "__main__":
    main()
