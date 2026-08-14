# HMR Morning Brief — Automated Newsletter

An automatic daily Bitcoin + macro newsletter in the Joe Consorti voice. Pulls
live data, auto-selects the day's most relevant charts, writes the analysis with
Claude, and sends through Beehiiv. Runs itself at 7 AM ET on GitHub Actions.

## How it works (the daily flow)

1. **collect_data.py** pulls live data: BRK (on-chain), Yahoo (macro),
   alternative.me (Fear & Greed), and your live monitor.json (composite score).
2. **chart_select.py** scores every candidate chart by how much it moved and how
   meaningful its reading is, then picks the top 4 (weekday) or 2 (weekend).
   `price_vs_levels` always leads. It also flags **big-news days**.
3. **render_charts.py** renders the selected charts as HMR-branded PNGs.
4. **write_prose.py** writes the narrative in your voice via the Claude API,
   using `voice_prompt.md` as the single source of voice truth.
5. **assemble_html.py** lays it all out in the Axel-Adler-style email.
6. **build_newsletter.py** orchestrates, then sends through Beehiiv —
   **auto-send on normal weekdays, lands as a draft when big news hits.**

## The three levers (edit these, nothing else)

- **Voice** → `voice_prompt.md`. Change how every future issue reads.
- **Structure / chart-selection rules** → `chart_select.py` (the `RULES` table)
  and `assemble_html.py` (the layout).
- **Schedule** → `.github/workflows/newsletter.yml` (the cron lines).

Push any change; it's live the next morning. No rebuild.

## Preview it right now (no keys needed)

```
pip install -r requirements.txt
python build_newsletter.py --dry-run
open out/preview.html
```

This generates the complete newsletter with real data and templated prose, so
you can tune voice and format before going live.

## Going live (three secrets, one time)

Add these as GitHub repo secrets (Settings → Secrets and variables → Actions):

- `ANTHROPIC_API_KEY` — from console.anthropic.com. Writes the prose. Pennies/day.
- `BEEHIIV_API_KEY` — from Beehiiv Settings → API.
- `BEEHIIV_PUB_ID` — your Beehiiv publication id (looks like `pub_xxxxx`).

Then the newsletter sends automatically at 7 AM ET. Weekends get a lighter
2-chart edition. Big-news days land as a draft for your glance instead of
auto-sending.

## Send behavior

- **Normal weekday / weekend** → publishes and emails automatically.
- **Big-news day** (5%+ daily BTC move, composite sitting on a band edge,
  Fear & Greed at an extreme, or a bond-vol spike) → lands as a Beehiiv **draft**
  with the reasons printed in the run log, so you can eyeball before sending.
  Tune the thresholds in `chart_select.detect_big_news`.

## Production note on chart hosting

The local preview inlines charts as base64 so it's self-contained. In
production, charts should be uploaded (e.g. committed to the monitor repo or an
image host) and their URLs passed to `assemble_html.assemble(..., inline_base64=False)`.
A simple option: commit the day's PNGs to the monitor's GitHub Pages repo and
reference `https://monitor.joeconsorti.com/newsletter/<date>/<chart>.png`.
Left as the one remaining wire-up since it depends on where you want them hosted.
