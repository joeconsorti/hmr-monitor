"""
build_newsletter.py — the orchestrator. Run this once each morning.

  python build_newsletter.py --dry-run     # local HTML preview, no keys needed
  python build_newsletter.py               # live: writes prose (Claude) + sends (Beehiiv)

Flow: collect data -> pick the day's charts -> render them -> write Joe-voice
prose -> assemble HTML -> send via Beehiiv (auto weekdays, draft on big news).

Env vars for live mode:
  ANTHROPIC_API_KEY   — writes the narrative
  BEEHIIV_API_KEY     — sends the email
  BEEHIIV_PUB_ID      — your publication id (pub_xxx)
Weekend editions are lighter (fewer charts). Big-news days land as a draft.
"""
import os
import sys
import json
import datetime
import urllib.request
import urllib.error

import collect_data
import chart_select as selector
import render_charts
import publish_charts
import write_prose
import assemble_html

OUTDIR = os.path.join(os.path.dirname(__file__), "out")


def is_weekend():
    return datetime.date.today().weekday() >= 5   # Sat=5, Sun=6


def send_beehiiv(html, subject, as_draft):
    """POST to Beehiiv Create Post. status must be explicit since Aug 6 2026:
    'confirmed' publishes/sends, 'draft' lands for review."""
    api_key = os.environ.get("BEEHIIV_API_KEY")
    pub_id = os.environ.get("BEEHIIV_PUB_ID")
    if not api_key or not pub_id:
        print("  ! BEEHIIV_API_KEY / BEEHIIV_PUB_ID not set — skipping send")
        return None
    payload = {
        "title": subject,
        "subtitle": "The Bitcoin Brief · From Joe Consorti",
        "body_content": html,
        "status": "draft" if as_draft else "confirmed",
        "email_settings": {"email_subject_line": subject},
    }
    req = urllib.request.Request(
        f"https://api.beehiiv.com/v2/publications/{pub_id}/posts",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read())
        print(f"  ok Beehiiv: {'DRAFT created' if as_draft else 'SENT'} (post {resp.get('data',{}).get('id','?')})")
        return resp
    except urllib.error.HTTPError as e:
        print(f"  ! Beehiiv send failed: HTTP {e.code} {e.reason} — {e.read().decode(errors='replace')}")
        return None
    except Exception as e:
        print(f"  ! Beehiiv send failed: {e}")
        return None


def main():
    dry = "--dry-run" in sys.argv
    weekend = is_weekend()
    os.makedirs(OUTDIR, exist_ok=True)

    print("1/6 collecting data...")
    data = collect_data.collect()

    print("2/6 selecting charts...")
    selected = selector.select_charts(data, n_weekday=4, n_weekend=3, is_weekend=weekend)
    big_news, reasons = selector.detect_big_news(data)
    print(f"     charts: {[s['label'] for s in selected]}")
    if big_news:
        print(f"     BIG NEWS: {reasons} -> will land as DRAFT")

    print("3/6 rendering charts...")
    charts = render_charts.render(selected, data, OUTDIR)

    print("4/6 publishing charts...")
    # In production, host charts in the monitor repo (served via GitHub Pages)
    # and reference them by URL. In dry-run, keep them inline so the local
    # preview is self-contained.
    charts = publish_charts.publish(charts, dry_run=dry)

    print("5/6 writing prose...")
    prose = write_prose.write(data, selected, dry_run=dry)

    print("6/6 assembling HTML...")
    # dry-run inlines images (self-contained preview); production uses hosted URLs
    html = assemble_html.assemble(prose, charts, data, inline_base64=dry)
    preview_path = os.path.join(OUTDIR, "preview.html")
    with open(preview_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"     preview: {preview_path}")

    subject = prose.get("headline", "The Bitcoin Brief")

    print("7/7 sending...")
    if dry:
        print("     DRY RUN — not sending. Open the preview to review.")
    else:
        # SAFETY SWITCH: set DRAFT_ONLY=1 (env var) to force every post to land
        # as a Beehiiv DRAFT instead of emailing the list. Use this for the very
        # first live runs so you can eyeball the real post in Beehiiv before it
        # ever reaches a subscriber. Remove the env var (or set it to 0) to go
        # fully live. Big-news days still draft automatically regardless.
        draft_only = os.environ.get("DRAFT_ONLY", "").strip() in ("1", "true", "yes", "on")
        as_draft = draft_only or big_news
        if draft_only:
            print("     DRAFT_ONLY is on — landing as a Beehiiv draft, NOT emailing the list.")
        send_beehiiv(html, subject, as_draft=as_draft)

    print("done.")
    return preview_path


if __name__ == "__main__":
    main()
