"""
assemble_html.py — assembles the prose + charts into the final email HTML,
styled after the Axel Adler morning-brief layout but in HMR branding.

Charts are embedded two ways:
  - inline_base64=True  : <img src="data:..."> so the local preview is fully
                          self-contained (used for --dry-run).
  - inline_base64=False : expects each chart dict to carry a hosted 'url'
                          (used in production once charts are uploaded).
Beehiiv accepts full custom HTML via the Create Post body_content field.
"""
import base64
import datetime

ORANGE = "#FD6F0B"


def _img_tag(chart, inline_base64):
    if inline_base64:
        with open(chart["path"], "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        src = f"data:image/png;base64,{b64}"
    else:
        src = chart.get("url", "")
    return (f'<img src="{src}" alt="{chart["label"]}" '
            f'style="width:100%;border-radius:10px;margin:6px 0 2px;display:block;">')


def _pretty_label(label):
    return {
        "price_vs_levels": "BTC Price vs Cost-Basis Levels",
        "sth_mvrv": "Short-Term Holder MVRV",
        "lth_sopr": "Long-Term Holder SOPR",
        "puell": "Puell Multiple",
        "mvrv": "MVRV Ratio",
        "fear_greed": "Fear & Greed",
        "gold": "Gold",
        "yields": "US 10-Year Yield",
        "move": "MOVE Index",
        "semis": "AI Trade vs Bitcoin",
        "sth_share": "STH Realized-Cap Share",
        "supply_in_profit": "Supply in Profit",
        "btc_gold": "Bitcoin / Gold Ratio",
    }.get(label, label.replace("_", " ").title())


def assemble(prose, charts, data, inline_base64=True):
    today = datetime.date.today().strftime("%B %-d, %Y")
    comp = data.get("composite")
    verdict = data.get("verdict", "")
    regime = data.get("regime", "")

    chart_sections = ""
    reads = prose.get("chart_reads", {})
    # charts list preserves selection order; price_vs_levels leads
    for ch in charts:
        label = ch["label"]
        read = reads.get(label, "")
        paras = "".join(f"<p style='margin:10px 0;line-height:1.6;color:#c9d1d9;'>{p.strip()}</p>"
                        for p in read.split("\n") if p.strip())
        chart_sections += f"""
        <div style="margin:26px 0;">
          <h3 style="color:#e6edf3;font-size:16px;margin:0 0 4px;">{_pretty_label(label)}</h3>
          {_img_tag(ch, inline_base64)}
          {paras}
        </div>"""

    draft_banner = ""
    if prose.get("_dry_run"):
        draft_banner = ("<div style='background:#2a1f16;border:1px solid #3a2a18;color:#e0a838;"
                        "padding:10px 14px;border-radius:8px;margin-bottom:18px;font-size:13px;'>"
                        "PREVIEW / DRY-RUN — prose is templated. Live issues are written by Claude.</div>")

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0d1117;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
<div style="max-width:640px;margin:0 auto;padding:28px 22px;background:#0d1117;color:#e6edf3;">

  {draft_banner}

  <div style="border-bottom:1px solid #1c2530;padding-bottom:16px;margin-bottom:22px;">
    <div style="color:{ORANGE};font-weight:700;font-size:15px;letter-spacing:1px;">THE BITCOIN BRIEF</div>
    <div style="color:#7d8896;font-size:12px;margin-top:3px;">{today} · from The Hard Money Room</div>
  </div>

  <h1 style="font-size:22px;line-height:1.3;margin:0 0 16px;color:#fff;">{prose.get('headline','')}</h1>

  <div style="background:#131a22;border:1px solid #1c2530;border-radius:10px;padding:16px 18px;margin-bottom:8px;">
    <div style="color:{ORANGE};font-size:11px;letter-spacing:1px;font-weight:700;margin-bottom:6px;">THE SIGNAL</div>
    <div style="display:flex;align-items:baseline;gap:10px;">
      <span style="font-size:34px;font-weight:800;color:#fff;">{comp}</span>
      <span style="color:#7d8896;">/ 100</span>
      <span style="color:#2dd4bf;font-weight:700;margin-left:8px;">{verdict}</span>
    </div>
    <div style="color:#9aa4b0;font-size:13px;margin-top:4px;">{regime}</div>
  </div>

  <div style="margin:22px 0;">
    <div style="color:{ORANGE};font-size:11px;letter-spacing:1px;font-weight:700;margin-bottom:6px;">TL;DR</div>
    <p style="margin:0;line-height:1.65;color:#c9d1d9;font-size:15px;">{prose.get('tldr','')}</p>
  </div>

  {chart_sections}

  <div style="background:#0f151c;border-left:3px solid {ORANGE};padding:14px 18px;margin:26px 0;border-radius:0 8px 8px 0;">
    <div style="color:{ORANGE};font-size:11px;letter-spacing:1px;font-weight:700;margin-bottom:6px;">WHAT TO WATCH</div>
    <p style="margin:0;line-height:1.6;color:#c9d1d9;">{prose.get('what_to_watch','')}</p>
  </div>

  <div style="background:#131a22;border:1px solid #1c2530;border-radius:10px;padding:18px;margin:26px 0;text-align:center;">
    <div style="color:#7d8896;font-size:11px;letter-spacing:1px;margin-bottom:8px;">THE ONE TAKEAWAY</div>
    <p style="margin:0;font-size:17px;line-height:1.5;color:#fff;font-weight:600;">{prose.get('takeaway','')}</p>
  </div>

  <div style="text-align:center;margin:30px 0 10px;">
    <a href="https://monitor.joeconsorti.com" style="display:inline-block;background:{ORANGE};color:#150a02;text-decoration:none;font-weight:700;padding:12px 26px;border-radius:8px;font-size:14px;">Open the live Cycle Monitor →</a>
  </div>

  <div style="border-top:1px solid #1c2530;margin-top:26px;padding-top:16px;color:#5a636e;font-size:11px;line-height:1.6;">
    The Hard Money Room · A Joe Consorti Media LLC production. Educational only, not financial advice.
    For full terms &amp; conditions, visit
    <a href="https://www.joeconsorti.com/terms" style="color:#7d8896;">joeconsorti.com/terms</a>.
  </div>

</div></body></html>"""
