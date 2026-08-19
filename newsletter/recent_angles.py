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


def record(headline, lead_label, date=None):
    """Append today's headline/lead topic, replacing any existing entry for
    the same date (so re-running the same day doesn't duplicate), and trim to
    the last KEEP days."""
    date = date or datetime.date.today().isoformat()
    try:
        with open(PATH, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except Exception:
        entries = []
    entries = [e for e in entries if e.get("date") != date]
    entries.append({"date": date, "headline": headline, "lead_label": lead_label})
    entries = entries[-KEEP:]
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
    return entries
