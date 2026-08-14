# The Bitcoin Brief — Go-Live Checklist

The engine is built and tested. Chart hosting is wired. Here is everything
left to make it send automatically at 7 AM ET.

## Architecture (how it works now)

The newsletter lives INSIDE your monitor repo as a `newsletter/` subfolder.
One repo, one place to manage. Each morning its own GitHub Action:

1. Reads the live data (same sources as the monitor + the built monitor.json)
2. Auto-selects the day's most relevant charts
3. Renders them, and commits them into `newsletter/charts/<date>/` — which your
   GitHub Pages already serves free at
   `monitor.joeconsorti.com/newsletter/charts/<date>/`
4. Writes the analysis in your voice via the Claude API
5. Assembles the email with those hosted chart URLs
6. Sends through Beehiiv (auto weekdays + lighter weekend, draft on big news)

It runs as its OWN Action, separate from the monitor's data build, so a
newsletter hiccup can never disrupt your core monitor.json refresh.

## Step 1 — Put the newsletter into the monitor repo

Copy this whole folder into your `hmr-monitor` repo so it sits at:

    hmr-monitor/
      index.html
      build_monitor.py
      monitor.json
      newsletter/          <-- this folder
        build_newsletter.py
        ...
      .github/workflows/
        daily.yml          (your existing monitor build)
        newsletter.yml      <-- move newsletter/.github/workflows/newsletter.yml here

IMPORTANT: GitHub only reads workflow files from `.github/workflows/` at the
repo ROOT. So move `newsletter/.github/workflows/newsletter.yml` up to the
repo's top-level `.github/workflows/` folder (next to your monitor's daily.yml).
The paths inside it already point at `newsletter/`.

## Step 2 — Add three repo secrets

In the hmr-monitor repo: Settings -> Secrets and variables -> Actions ->
New repository secret. Add:

  ANTHROPIC_API_KEY   from console.anthropic.com  (writes the prose; pennies/day)
  BEEHIIV_API_KEY     from Beehiiv Settings -> API
  BEEHIIV_PUB_ID      your Beehiiv publication id (pub_xxxxxxxx)

## Step 3 — Test it once, by hand

In the repo's Actions tab, open "The Bitcoin Brief" and click "Run workflow".
Because of the 7 AM guard, a manual run always proceeds. Watch it:

  - it builds, commits the charts, and (with real keys) sends or drafts.
  - check the newsletter-preview artifact on the run to see the exact HTML.

Start SAFE: to make the very first live run land as a draft instead of emailing
your whole list, either run it on a day the big-news detector trips, or set
BEEHIIV secrets after you've eyeballed one artifact preview. Once you're happy,
let it run on schedule.

## Step 4 — Preview anytime, no keys

    cd newsletter
    python build_newsletter.py --dry-run
    open out/preview.html

Generates the full brief with real data and templated prose. Use it to tweak
voice (voice_prompt.md) and format before every change.

## The three levers (edit these, nothing else)

  voice_prompt.md   -> how it reads
  chart_select.py   -> which charts trigger (the RULES table)
  newsletter.yml    -> when it sends

## Send behavior

  Normal weekday / weekend -> publishes and emails automatically
  Big-news day             -> lands as a Beehiiv draft for your glance
                              (thresholds in chart_select.detect_big_news)
