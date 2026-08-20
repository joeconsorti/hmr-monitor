"""
recent_angles.py — tracks the last several days' headlines and lead topics so
write_prose.py can steer the model away from repeating the same angle.

Stored at newsletter/recent_angles.json and committed back to the repo by the
workflow (same pattern as the chart images), since each CI run starts from a
fresh checkout and has no other memory of what ran yesterday.
"""
import os
import json
import datetime

PATH = os.path.join(os.path.dirname(__file__), "recent_angles.json")
KEEP = 7


def load_recent(n=KEEP):
    try:
        with open(PATH, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except Exception:
        return []
    return entries[-n:]


def record(headline, lead_label, chart_labels=None, date=None):
    """Append today's headline/lead topic/full chart lineup, replacing any
    existing entry for the same date (so re-running the same day doesn't
    duplicate), and trim to the last KEEP days. chart_labels is the day's
    full list of selected chart labels, used by chart_select.py's
    recent_sets hard-exclusion so the lineup can't repeat day to day.

    If an entry already exists for this date (e.g. a special issue ran the
    same day as the daily brief), its chart_labels are merged into the new
    entry rather than discarded -- otherwise the second write on a given day
    silently erases the first write's chart lineup from rotation history,
    letting tomorrow's hard-exclusion miss charts that really did run today."""
    date = date or datetime.date.today().isoformat()
    try:
        with open(PATH, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except Exception:
        entries = []
    existing = next((e for e in entries if e.get("date") == date), None)
    entries = [e for e in entries if e.get("date") != date]
    merged_labels = list(chart_labels or [])
    if existing:
        for label in existing.get("chart_labels") or []:
            if label not in merged_labels:
                merged_labels.append(label)
    entries.append({"date": date, "headline": headline, "lead_label": lead_label,
                     "chart_labels": merged_labels})
    entries = entries[-KEEP:]
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
    return entries
