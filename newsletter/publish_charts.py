"""
publish_charts.py — hosts the day's charts so Beehiiv emails can load them.

Strategy: copy the rendered PNGs into the monitor repo under
  newsletter/charts/<YYYY-MM-DD>/
then (in CI) that repo is committed and served free via GitHub Pages at
  https://monitor.joeconsorti.com/newsletter/charts/<YYYY-MM-DD>/<file>.png

Each chart dict comes back stamped with a public `url`, which assemble_html
uses in url mode (inline_base64=False). Dated folders mean past issues keep
working forever and nothing overwrites.

Two modes:
  local copy (default): copies files into the repo working tree. The GitHub
      Action commits+pushes them (see newsletter.yml). Use in production.
  --dry-run: skips copying, just stamps a would-be URL so you can preview the
      final URL-mode HTML without touching the repo.

Config via env vars (with sensible defaults):
  MONITOR_REPO_DIR  path to the checked-out hmr-monitor repo (default ../hmr-monitor)
  PAGES_BASE_URL    public base (default https://monitor.joeconsorti.com)
"""
import os
import shutil
import datetime


def publish(charts, dry_run=False):
    base_url = os.environ.get("PAGES_BASE_URL", "https://monitor.joeconsorti.com").rstrip("/")
    # Newsletter lives inside the monitor repo at newsletter/, so the repo root
    # is one level up from this file's folder. MONITOR_REPO_DIR overrides in CI.
    repo_dir = os.environ.get("MONITOR_REPO_DIR",
                              os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    date = datetime.date.today().isoformat()
    rel_dir = f"newsletter/charts/{date}"
    public_dir = f"{base_url}/{rel_dir}"

    if not dry_run:
        dest = os.path.join(repo_dir, rel_dir)
        os.makedirs(dest, exist_ok=True)

    out = []
    for ch in charts:
        fname = os.path.basename(ch["path"])
        url = f"{public_dir}/{fname}"
        if not dry_run:
            try:
                shutil.copy2(ch["path"], os.path.join(repo_dir, rel_dir, fname))
            except Exception as e:
                print(f"  ! could not copy {fname} into repo: {e}")
        stamped = dict(ch)
        stamped["url"] = url
        out.append(stamped)

    if dry_run:
        print(f"     (dry-run) charts would be hosted at {public_dir}/")
    else:
        print(f"     charts staged for commit in {rel_dir}/ ({len(out)} files)")
    return out
