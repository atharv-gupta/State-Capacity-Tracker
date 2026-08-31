#!/usr/bin/env python3
"""State Capacity Tracker — dedupe/condense stage (clean layer).

Reads the last N days of 'Raw Events' (one row per article), clusters rows
that describe the same underlying government action into a single EVENT
(one government action shows up across many outlets — docs/SPEC.md §4 principle 1),
and rebuilds that window of the clean 'Events' table: one row per event with
all source URLs/outlets merged.

Usage:
    python dedupe.py                # cluster the last 7 days
    python dedupe.py --days 14
    python dedupe.py --dry-run      # show clusters, don't touch Airtable
"""

import argparse
import concurrent.futures
import json
import os
import sys
import uuid
from datetime import date, timedelta

from anthropic import Anthropic
from dotenv import load_dotenv
from pyairtable import Api

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")
if not all([ANTHROPIC_API_KEY, AIRTABLE_TOKEN, AIRTABLE_BASE_ID]):
    sys.exit("Missing env vars; see .env_example.")

RAW_TABLE = "Raw Events"
CLEAN_TABLE = "Events"
MODEL = "claude-sonnet-4-6"   # stronger model for synthesis + classification
WORKERS = 6

# The classification rubric, loaded once at startup and sent as a cached system
# prompt on every classify_event call (see classify_event).
from tracker.paths import RUBRICS

RUBRIC_PATH = os.path.join(RUBRICS, "rubric.md")
with open(RUBRIC_PATH, encoding="utf-8") as _fh:
    RUBRIC = _fh.read()

# Competency is a SINGLE value per event (was multi-select "pillars"); "none" is a
# An event may match more than one (e.g. oversight of a failing IT system is both
# digital + incentives). Matching NONE is the common case — stored as an empty list.
COMPETENCY_CHOICES = ["civil-service", "procedure", "digital", "incentives"]
# Descriptive topic tags, independent of competency (rubrics/rubric.md "Topic tags").
TOPIC_TAG_CHOICES = [
    # capacity tags
    "it-modernization", "ai", "data-privacy", "cybersecurity", "broadband",
    "benefits-systems", "procurement", "occupational-licensing", "permitting",
    "housing-land-use", "regulatory-reform", "hiring-recruitment",
    "compensation-pensions", "labor-relations", "telework-rto", "layoffs-rif",
    "reorganization", "transparency", "study-commission",
    # sector tags
    "data-center", "tax-incentives", "energy-utility", "health-human-services",
    "higher-ed", "k12-education", "child-welfare",
]
ACTIVITY_TYPE_CHOICES = [
    "bill-introduced", "bill-passed", "veto", "EO", "rulemaking", "appointment",
    "reorg", "RFP/procurement", "budget", "program-launch", "audit/report",
]
ACTOR_TYPE_CHOICES = [
    "governor", "legislature", "state agency", "statewide official",
    "board/commission", "court", "university system", "other",
]

# Schema for the clean events table. Field names must match build_event_row's
# keys EXACTLY — dedupe writes rows with those keys and no name remapping. Used by
# ensure_clean_table to create a fresh table (e.g. Events2) or backfill columns.
CLEAN_FIELDS = [
    {"name": "Name", "type": "singleLineText"},               # primary field
    {"name": "Notes", "type": "multilineText"},
    {"name": "event_id", "type": "singleLineText"},
    {"name": "date", "type": "date", "options": {"dateFormat": {"name": "iso"}}},
    {"name": "state", "type": "singleLineText"},
    {"name": "competency", "type": "multipleSelects",
     "options": {"choices": [{"name": p} for p in COMPETENCY_CHOICES]}},
    {"name": "relevance", "type": "number", "options": {"precision": 0}},
    {"name": "topic_tags", "type": "multipleSelects",
     "options": {"choices": [{"name": t} for t in TOPIC_TAG_CHOICES]}},
    {"name": "activity_type", "type": "singleSelect",
     "options": {"choices": [{"name": a} for a in ACTIVITY_TYPE_CHOICES]}},
    {"name": "actor_type", "type": "singleSelect",
     "options": {"choices": [{"name": a} for a in ACTOR_TYPE_CHOICES]}},
    {"name": "gov_actor", "type": "singleLineText"},
    {"name": "headline", "type": "multilineText"},
    {"name": "why_it_matters", "type": "multilineText"},
    {"name": "source_urls", "type": "multilineText"},
    {"name": "source_outlets", "type": "singleLineText"},
    {"name": "source_type", "type": "singleLineText"},        # comma-joined merge
    {"name": "Status", "type": "singleLineText"},
    {"name": "article_count", "type": "number", "options": {"precision": 0}},
]

SYSTEM_PROMPT = f"""You deduplicate rows in a state-government activity tracker.
You receive a list of articles (rows) about ONE state's government from the
past week. Multiple rows often describe the SAME underlying government action
reported by different outlets. Cluster them into distinct EVENTS and synthesize
each one.

Your job is clustering + synthesis ONLY. Do NOT judge which capacity an event
touches or how significant it is — a separate classification step handles that.

Rules:
- Two rows belong to the same event only if they describe the same underlying
  government action (same bill, same appointment, same layoff, same contract),
  not merely the same topic.
- The same bill/action at different procedural stages within the week is ONE
  event at its latest stage; note the progression in the notes.
- Every input row id must appear in exactly one event.
- A row that matches nothing is its own single-row event.

Output ONLY this JSON (no fences, no preamble):
{{
  "events": [
    {{
      "member_ids": ["rec...", "rec..."],
      "name": "concise title of the action, 5-10 words, no state name, sentence case",
      "headline": "one-line what happened, best synthesis of the member rows",
      "notes": "1-2 plain sentences: what happened and why it matters for state capacity",
      "date": "YYYY-MM-DD of the government action (earliest credible)",
      "activity_type": "one of: {' | '.join(ACTIVITY_TYPE_CHOICES)}",
      "gov_actor": "which body/office acted",
      "actor_type": "one of: {' | '.join(ACTOR_TYPE_CHOICES)}",
      "why_it_matters": "one line for the digest, empty string if none",
      "status": "optional: introduced | enacted | etc., empty string if N/A"
    }}
  ]
}}"""


def parse_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    start = text.find("{")
    end = text.rfind("}")
    return json.loads(text[start:end + 1])


def cluster_state(client, state, rows):
    """rows: list of (record_id, fields). Returns the model's event list."""
    payload = [{
        "id": rid,
        "date": f.get("date", ""),
        "headline": f.get("headline", ""),
        "gov_actor": f.get("gov_actor", ""),
        "activity_type": f.get("activity_type", ""),
        "actor_type": f.get("actor_type", ""),
        "notes": f.get("Notes", ""),
        "status": f.get("Status") or f.get("status", ""),
        "outlet": f.get("source_outlets", ""),
        "url": f.get("source_urls", ""),
    } for rid, f in rows]
    resp = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": json.dumps({"state": state, "rows": payload})}],
    )
    return parse_json_response(resp.content[0].text)["events"]


def classify_event(client, event):
    """Classify ONE synthesized event against rubrics/rubric.md.

    Returns {"competencies": [...], "relevance", "topic_tags"}. competencies is a
    list of zero or more (empty = fits none). rubrics/rubric.md is sent as the cached
    system prompt (identical across every call, so it caches), and the synthesized
    event fields go in the user message. Runs over EVERY event — including
    single-article ones, which skip the clustering call but still need a read.
    """
    payload = {
        "name": event.get("name", ""),
        "headline": event.get("headline", ""),
        "notes": event.get("notes", ""),
        "activity_type": event.get("activity_type", ""),
        "gov_actor": event.get("gov_actor", ""),
        "actor_type": event.get("actor_type", ""),
    }
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=[{
            "type": "text",
            "text": RUBRIC,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": json.dumps(payload)}],
    )
    return parse_json_response(resp.content[0].text)


def build_event_row(state, ev, members):
    urls, outlets, types = [], [], []
    for _, f in members:
        for u in (f.get("source_urls") or "").splitlines():
            if u.strip() and u.strip() not in urls:
                urls.append(u.strip())
        o = f.get("source_outlets", "")
        if o and o not in outlets:
            outlets.append(o)
        st = f.get("source_type", "")
        if st and st not in types:
            types.append(st)

    row = {
        "Name": f"{state} — {(ev.get('name') or ev.get('headline', '')).strip()}",
        "Notes": (ev.get("notes") or "").strip(),
        "event_id": str(uuid.uuid4()),
        "state": state,
        "headline": ev.get("headline", ""),
        "gov_actor": ev.get("gov_actor", ""),
        "why_it_matters": ev.get("why_it_matters", ""),
        "Status": ev.get("status", ""),
        "source_urls": "\n".join(urls),
        "source_outlets": ", ".join(outlets),
        "source_type": ", ".join(types),
        "article_count": len(members),
    }

    # Classification (from classify_event, attached to ev before this call).
    # competency is a list of zero or more; empty list = fits none of the four.
    comps = ev.get("competencies") or []
    if isinstance(comps, str):
        comps = [comps]
    comps = [c for c in comps if c in COMPETENCY_CHOICES]
    row["competency"] = comps

    # relevance 1-3, replacing the old 1-5 significance; no-competency events get no score.
    if comps:
        try:
            rel = int(ev.get("relevance") or 0)
            if 1 <= rel <= 3:
                row["relevance"] = rel
        except (TypeError, ValueError):
            pass

    tags = ev.get("topic_tags") or []
    if isinstance(tags, str):
        tags = [tags]
    tags = [t for t in tags if t in TOPIC_TAG_CHOICES]
    if tags:
        row["topic_tags"] = tags

    d = ev.get("date", "")
    if len(d) == 10 and d[4] == "-" and d[7] == "-":
        row["date"] = d
    else:
        dates = sorted(f.get("date", "") for _, f in members if f.get("date"))
        if dates:
            row["date"] = dates[0]

    at = ev.get("activity_type", "")
    if at in ACTIVITY_TYPE_CHOICES:
        row["activity_type"] = at

    actor = ev.get("actor_type", "")
    if actor not in ACTOR_TYPE_CHOICES:
        actor = next((f.get("actor_type") for _, f in members
                      if f.get("actor_type") in ACTOR_TYPE_CHOICES), "other")
    row["actor_type"] = actor

    return row


def ensure_clean_table(base, table_name):
    """Return the clean events Table, creating it (with CLEAN_FIELDS) if it does
    not exist, or adding any missing columns if it does. Lets us point dedupe at
    a fresh table like Events2 for side-by-side review."""
    existing = next((t for t in base.schema().tables if t.name == table_name), None)
    if existing is None:
        created = base.create_table(table_name, fields=CLEAN_FIELDS)
        print(f"Created Airtable table '{table_name}'")
        tid = getattr(created, "id", None)
        return base.table(tid) if tid else base.table(table_name)
    table = base.table(existing.id)
    have = {f.name for f in existing.fields}
    for f in CLEAN_FIELDS:
        if f["name"] in have:
            continue
        opts = f.get("options")
        table.create_field(f["name"], f["type"], options=opts) if opts \
            else table.create_field(f["name"], f["type"])
        print(f"  added field '{f['name']}' to '{table_name}'")
    return table


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=7, help="window in days (default 7)")
    ap.add_argument("--all", action="store_true",
                    help="process every raw row, ignoring the date window")
    ap.add_argument("--clean-table", default=CLEAN_TABLE,
                    help=f"clean table to (re)build (default {CLEAN_TABLE!r})")
    ap.add_argument("--dry-run", action="store_true", help="show clusters, don't write")
    args = ap.parse_args()

    min_date = "" if args.all else (date.today() - timedelta(days=args.days)).isoformat()

    api = Api(AIRTABLE_TOKEN)
    base = api.base(AIRTABLE_BASE_ID)
    schema = base.schema()
    raw = base.table(next(t.id for t in schema.tables if t.name == RAW_TABLE))

    rows = [(r["id"], r["fields"]) for r in raw.all()
            if (r["fields"].get("date") or "") >= min_date]
    print(f"{len(rows)} raw rows" + (" (all)" if args.all else f" since {min_date}"))
    if not rows:
        return

    by_state = {}
    for rid, f in rows:
        by_state.setdefault(f.get("state", "??"), []).append((rid, f))

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    all_events, errors = [], []

    def work(item):
        state, srows = item
        if len(srows) == 1:
            rid, f = srows[0]
            ev = {
                "member_ids": [rid],
                "name": (f.get("Name", "").split("—", 1) + [""])[1].strip() or f.get("headline", ""),
                "headline": f.get("headline", ""),
                "notes": f.get("Notes", ""),
                "date": f.get("date", ""),
                "activity_type": f.get("activity_type", ""),
                "gov_actor": f.get("gov_actor", ""),
                "actor_type": f.get("actor_type", ""),
                "why_it_matters": f.get("why_it_matters", ""),
                "status": f.get("Status") or f.get("status", ""),
            }
            return state, [ev], srows
        return state, cluster_state(client, state, srows), srows

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(work, item): item[0] for item in by_state.items()}
        for fut in concurrent.futures.as_completed(futs):
            state = futs[fut]
            try:
                state, events, srows = fut.result()
            except Exception as e:
                errors.append(f"{state}: {e}")
                print(f"  ERROR {state} — {e}")
                continue
            by_id = dict(srows)
            ids_seen = set()
            for ev in events:
                members = [(rid, by_id[rid]) for rid in ev.get("member_ids", []) if rid in by_id]
                if not members:
                    continue
                ids_seen.update(rid for rid, _ in members)
                all_events.append((state, ev, members))
            orphans = [rid for rid in by_id if rid not in ids_seen]
            for rid in orphans:   # model missed a row — keep it as its own event
                f = by_id[rid]
                all_events.append((state, {
                    "member_ids": [rid], "headline": f.get("headline", ""),
                    "name": f.get("headline", ""), "notes": f.get("Notes", ""),
                    "date": f.get("date", ""),
                    "activity_type": f.get("activity_type", ""),
                    "gov_actor": f.get("gov_actor", ""),
                    "actor_type": f.get("actor_type", ""),
                    "why_it_matters": f.get("why_it_matters", ""),
                    "status": f.get("Status") or f.get("status", ""),
                }, [(rid, f)]))
            merged = sum(1 for ev in events if len(ev.get("member_ids", [])) > 1)
            print(f"  {state}: {len(srows)} articles -> {len(events) + len(orphans)} events"
                  + (f" ({merged} merged clusters)" if merged else ""))

    print(f"\n{len(rows)} raw articles -> {len(all_events)} events")

    # Classify every event against rubrics/rubric.md — single-article events included.
    # Mutates each ev in place with competencies / relevance / topic_tags.
    def classify_one(triplet):
        state, ev, _members = triplet
        try:
            result = classify_event(client, ev)
        except Exception as e:
            errors.append(f"classify {state}: {e}")
            print(f"  ERROR classifying {state} — {e}")
            result = {}
        comps = result.get("competencies") or []
        ev["competencies"] = comps if isinstance(comps, list) else [comps]
        ev["relevance"] = result.get("relevance") or 0
        tags = result.get("topic_tags") or []
        ev["topic_tags"] = tags if isinstance(tags, list) else [tags]

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(classify_one, all_events))
    print(f"Classified {len(all_events)} events against rubrics/rubric.md")

    if args.dry_run:
        for state, ev, members in sorted(all_events, key=lambda x: (x[0], x[1].get("date", ""))):
            tag = f"x{len(members)}" if len(members) > 1 else "  "
            comp = "+".join(ev.get("competencies", [])) or "none"
            rel = ev.get("relevance") or ""
            tags = ",".join(ev.get("topic_tags", []))
            label = f"[{comp}{(' ' + str(rel)) if rel else ''}]"
            print(f"  {state} {ev.get('date','??')} {tag} {label:>22} {ev.get('headline','')[:70]}"
                  + (f"  #{tags}" if tags else ""))
        return

    # Rebuild the clean table's window: delete clean rows in range, write fresh
    clean = ensure_clean_table(base, args.clean_table)
    stale = [r["id"] for r in clean.all()
             if (r["fields"].get("date") or "") >= min_date or not r["fields"].get("date")]
    if stale:
        clean.batch_delete(stale)
        print(f"Cleared {len(stale)} stale clean rows in window")

    created = 0
    for state, ev, members in all_events:
        try:
            clean.create(build_event_row(state, ev, members), typecast=True)
            created += 1
        except Exception as e:
            errors.append(f"write {state}: {e}")
            print(f"  ERROR writing {state} — {e}")
    print(f"Wrote {created} events to '{args.clean_table}'")

    if errors:
        print("\n--- ERRORS ---")
        for e in errors:
            print(f"  {e}")


if __name__ == "__main__":
    main()
