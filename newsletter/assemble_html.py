"""
assemble_html.py — assembles the prose + charts into the final email HTML,
styled after the Axel Adler morning-brief layout but in HMR branding.

The brief is macro-first: THE MACRO section leads, THE PAYOFF (Bitcoin)
section narrows into it as the causal result. Charts are embedded inline
within each section's paragraphs (no per-chart titles), split macro vs
Bitcoin via chart_select.MACRO_LABELS.

Charts are embedded two ways:
  - inline_base64=True  : <img src="data:..."> so the local preview is fully
                          self-contained (used for --dry-run).
  - inline_base64=False : expects each chart dict to carry a hosted 'url'
                          (used in production once charts are uploaded).
Beehiiv accepts full custom HTML via the Create Post body_content field.
"""
import base64
import datetime

from chart_select import MACRO_LABELS

ORANGE = "#FD6F0B"


def _img_tag(chart, inline_base64):
    if inline_base64:
        with open(chart["path"], "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        src = f"data:image/png;base64,{b64}"
    else:
        src = chart.get("url", "")
    return (f'<img src="{src}" alt="{chart["label"]}" '
            f'style="width:100%;border-radius:10px;margin:6px 0;">')


def _interleave(paragraphs, charts, inline_base64):
    """Render a section's paragraphs with chart images woven in: each chart
    lands right after the paragraph of the same index, so the picture always
    follows the point it illustrates. Leftover charts (more charts than
    paragraphs) land at the end; leftover paragraphs (more paragraphs than
    charts) run on after the last image."""
    html = ""
    for i, p in enumerate(paragraphs):
        html += f"<p style='margin:12px 0;line-height:1.6;color:#c9d1d9;'>{p.strip()}</p>"
        if i < len(charts):
            html += _img_tag(charts[i], inline_base64)
    for extra in charts[len(paragraphs):]:
        html += _img_tag(extra, inline_base64)
    return html


def assemble(prose, charts, data, inline_base64=True):
    now = datetime.date.today()
    today = f"{now:%B} {now.day}, {now:%Y}"
    comp = data.get("composite")
    verdict = data.get("verdict", "")
    oc = data.get("onchain", {})
    fg = data.get("fear_greed") or {}
    price = oc.get("price")

    macro_charts = [c for c in charts if c["label"] in MACRO_LABELS]
    bitcoin_charts = [c for c in charts if c["label"] not in MACRO_LABELS]
    macro_html = _interleave(prose.get("macro_paragraphs", []), macro_charts, inline_base64)
    bitcoin_html = _interleave(prose.get("bitcoin_paragraphs", []), bitcoin_charts, inline_base64)

    draft_banner = ""
    if prose.get("_dry_run"):
        draft_banner = ("<div style='background:#2a1f16;border:1px solid #3a2a18;color:#e0a838;"
                        "padding:10px 14px;border-radius:8px;margin-bottom:18px;font-size:13px;'>"
                        "PREVIEW / DRY-RUN — prose is templated. Live issues are written by Claude.</div>")

    price_line = f"BTC ${price:,.0f}" if price else "BTC n/a"
    fg_line = f"Fear &amp; Greed: {fg['value']} ({fg['label']})" if fg else ""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0d1117;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
<div style="max-width:640px;margin:0 auto;padding:28px 22px;background:#0d1117;color:#e6edf3;">

  {draft_banner}

  <div style="border-bottom:1px solid #1c2530;padding-bottom:16px;margin-bottom:24px;">
    <div style="color:{ORANGE};font-weight:800;font-size:17px;letter-spacing:1px;">THE BITCOIN BRIEF</div>
    <div style="color:#7d8896;font-size:12px;margin-top:3px;">{today} · From Joe Consorti</div>
  </div>

  <h1 style="font-size:24px;line-height:1.3;margin:0 0 18px;color:#fff;">{prose.get('headline','')}</h1>

  <div style="background:#131a22;border:1px solid #1c2530;border-radius:10px;padding:14px 18px;margin-bottom:22px;display:flex;justify-content:space-between;align-items:center;">
    <div>
      <div style="color:{ORANGE};font-size:10px;letter-spacing:1px;font-weight:700;">CYCLE MONITOR</div>
      <div style="font-size:15px;color:#e6edf3;margin-top:2px;"><span style="font-size:26px;font-weight:800;color:#fff;">{comp}</span> <span style="color:#7d8896;">/100</span> · <span style="color:#2dd4bf;font-weight:700;">{verdict.upper()}</span></div>
    </div>
    <div style="text-align:right;color:#9aa4b0;font-size:12px;">
      {price_line}<br>{fg_line}
    </div>
  </div>

  <div style="margin:0 0 26px;">
    <div style="color:{ORANGE};font-size:11px;letter-spacing:1px;font-weight:700;margin-bottom:6px;">THE TL;DR</div>
    <p style="margin:0;line-height:1.65;color:#c9d1d9;font-size:15.5px;">{prose.get('tldr','')}</p>
  </div>

  <div style="margin:28px 0;">
    <div style="color:{ORANGE};font-size:11px;letter-spacing:1px;font-weight:700;margin-bottom:4px;">THE MACRO</div>
    <h2 style="font-size:18px;color:#fff;margin:0 0 10px;">{prose.get('macro_headline','')}</h2>
    {macro_html}
  </div>

  <div style="margin:28px 0;">
    <div style="color:{ORANGE};font-size:11px;letter-spacing:1px;font-weight:700;margin-bottom:4px;">THE PAYOFF</div>
    <h2 style="font-size:18px;color:#fff;margin:0 0 10px;">{prose.get('bitcoin_headline','')}</h2>
    {bitcoin_html}
  </div>

  <div style="background:#0f151c;border-left:3px solid {ORANGE};padding:16px 18px;margin:28px 0;border-radius:0 8px 8px 0;">
    <div style="color:{ORANGE};font-size:11px;letter-spacing:1px;font-weight:700;margin-bottom:8px;">WHAT TO WATCH</div>
    <p style="margin:0 0 10px;line-height:1.6;color:#c9d1d9;">{prose.get('watch_macro','')}</p>
    <p style="margin:0;line-height:1.6;color:#c9d1d9;">{prose.get('watch_price','')}</p>
  </div>

  <div style="background:#131a22;border:1px solid #1c2530;border-radius:10px;padding:20px;margin:28px 0;text-align:center;">
    <div style="color:#7d8896;font-size:11px;letter-spacing:1px;margin-bottom:10px;">THE ONE TAKEAWAY</div>
    <p style="margin:0;font-size:18px;line-height:1.5;color:#fff;font-weight:600;">{prose.get('takeaway','')}</p>
  </div>

  <div style="background:linear-gradient(135deg,#1a0f06,#0d1117);border:1px solid {ORANGE};border-radius:12px;padding:26px 24px;margin:32px 0 20px;text-align:center;">
    <div style="color:{ORANGE};font-size:12px;letter-spacing:1px;font-weight:800;margin-bottom:10px;">JOIN THE HARD MONEY ROOM</div>
    <p style="margin:0 0 8px;font-size:19px;color:#fff;font-weight:700;line-height:1.35;">You just read the summary. The room is where I show my work.</p>
    <p style="margin:0 0 18px;font-size:14.5px;color:#c9d1d9;line-height:1.6;">Every chart in this brief, live and updated daily. Weekly live calls where I walk through the whole macro and Bitcoin picture in real time and answer your questions directly. Daily chart drops, the full cycle dashboard, and the exact levels I'm watching. This newsletter is the appetizer. The Hard Money Room is the table.</p>
    <a href="https://www.skool.com/the-hard-money-room" style="display:inline-block;background:{ORANGE};color:#150a02;text-decoration:none;font-weight:800;padding:14px 34px;border-radius:8px;font-size:15px;">Join the Hard Money Room →</a>
    <div style="color:#7d8896;font-size:12px;margin-top:14px;">Come see everything I can't fit in a morning email.</div>
  </div>

  <div style="text-align:center;margin:22px 0;">
    <a href="https://monitor.joeconsorti.com" style="color:#9aa4b0;text-decoration:none;font-size:13px;border:1px solid #1c2530;border-radius:8px;padding:9px 20px;display:inline-block;">Or open the free live Cycle Monitor →</a>
  </div>

  <div style="border-top:1px solid #1c2530;margin-top:26px;padding-top:16px;color:#5a636e;font-size:11px;line-height:1.6;">
    The Bitcoin Brief · From Joe Consorti. Educational only, not financial advice.
    For full terms &amp; conditions, visit
    <a href="https://www.joeconsorti.com/terms" style="color:#7d8896;">joeconsorti.com/terms</a>.
  </div>

</div></body></html>"""
