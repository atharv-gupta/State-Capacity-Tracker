#!/usr/bin/env python3
"""Congressional tracker — cluster + classify (clean layer).

Reads 'Congress Raw', clusters rows describing the same underlying action into
one EVENT, classifies each event against the federal-capacity rubric, and
upserts into 'Congress Events'.

Two deliberate differences from the state pipeline's dedupe.py:

1. The window filters on `ingested_at`, not `date`. dedupe.py windows on the
   action date the classifier produced, so an item ingested today about an
   action six weeks ago falls outside every future window and never clusters.

2. This upserts on a content-derived event_id instead of deleting the window
   and rewriting it. Human review lives in Airtable (review_status,
   reviewer_notes); a delete-then-rewrite would erase it nightly.

Usage:
    python congress_dedupe.py --days 21
    python congress_dedupe.py --all --dry-run     # reclassify everything
    python congress_dedupe.py --days 7 --clean-table "Congress Events2"
"""

import argparse
import hashlib
import os
import sys
from datetime import date, datetime, timedelta, timezone

from anthropic import Anthropic
from dotenv import load_dotenv
from pyairtable import Api

import congress_llm
import congress_schema as cs
import congress_sources
from airtable_util import ensure_table, upsert

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")

MODEL = congress_llm.MODEL_CLASSIFY
WORKERS = congress_llm.WORKERS

CLUSTER_SYSTEM = f"""You deduplicate rows in a congressional activity tracker.

You receive rows about ONE committee's orbit from a recent window. Multiple
rows often describe the SAME underlying action — a majority office, a minority
office, and a member's office all writing up one markup, or several outlets
covering one GAO report. Cluster them into distinct EVENTS and synthesize each.

Your job is clustering + synthesis ONLY. Do NOT judge which capacity an event
touches or how relevant it is — a separate classification step handles that.

Rules:
- Two rows belong to the same event only if they describe the same underlying
  action (same bill at the same stage, same hearing, same letter, same report),
  not merely the same topic. Two different GAO reports are two events even if
  both concern federal workforce.
- Majority and minority write-ups of one committee action are ONE event.
  Synthesize both framings neutrally rather than adopting either.
- The same bill at different stages within the window is ONE event at its
  latest stage; note the progression in the summary.
- Every input row id must appear in exactly one event.
- A row that matches nothing is its own single-row event.

Output ONLY this JSON (no fences, no preamble):
{{
  "events": [
    {{
      "member_ids": ["rec...", "rec..."],
      "name": "concise title of the action, 5-10 words, sentence case",
      "headline": "one line: what happened, best synthesis of the member rows",
      "summary": "2-3 plain sentences: what happened and what it would actually do",
      "why_it_matters": "one line for a RAF reader, empty string if none",
      "date": "YYYY-MM-DD of the action (earliest credible)",
      "activity_type": "one of: {' | '.join(cs.ACTIVITY_TYPE_CHOICES)}",
      "actor": "which committee, member, or agency acted",
      "bill_refs": "bill numbers involved, or \\"\\"",
      "status": "optional stage note, empty string if N/A"
    }}
  ]
}}
"""

CLASSIFY_SYSTEM = congress_llm.RUBRIC_SYSTEM + """

---

# Output for this task

You are given ONE congressional event. Classify it.

Output ONLY this JSON, no fences:
{ "competencies": ["digital", "incentives"], "relevance": 3, "topic_tags": ["it-modernization"] }

For a non-fit: { "competencies": [], "relevance": 0, "topic_tags": [] }
"""


def event_id_for(urls):
    """Stable id from the member source URLs. Same set of sources -> same id
    across runs, so the upsert lands on the existing row and its review
    annotations survive."""
    joined = "\n".join(sorted(u for u in urls if u))
    return hashlib.sha1(joined.encode()).hexdigest()[:16]


def cluster(client, committee, rows):
    payload = {
        "committee": committee,
        "rows": [{
            "id": rid,
            "name": f.get("Name", ""),
            "headline": f.get("headline", ""),
            "notes": f.get("notes", ""),
            "date": f.get("date", ""),
            "source": f.get("source", ""),
            "party_source": f.get("party_source", ""),
            "activity_type": f.get("activity_type", ""),
            "bill_refs": f.get("bill_refs", ""),
        } for rid, f in rows],
    }
    out = congress_llm.call(client, MODEL, CLUSTER_SYSTEM, payload, max_tokens=8000)
    return out.get("events") or []


def classify_event(client, event):
    return congress_llm.call(client, MODEL, CLASSIFY_SYSTEM, {
        "name": event.get("name", ""),
        "headline": event.get("headline", ""),
        "summary": event.get("summary", ""),
        "activity_type": event.get("activity_type", ""),
        "actor": event.get("actor", ""),
        "committee": event.get("_committee", ""),
        "bill_refs": event.get("bill_refs", ""),
    }, max_tokens=600)


def single_row_event(rid, f):
    """A committee with one row in the window skips the clustering call —
    the same shortcut dedupe.py takes, and most of the volume here."""
    return {
        "member_ids": [rid],
        "name": (f.get("Name") or "").split(" — ", 1)[-1],
        "headline": f.get("headline", ""),
        "summary": f.get("notes", ""),
        "why_it_matters": "",
        "date": f.get("date", ""),
        "activity_type": f.get("activity_type", ""),
        "actor": f.get("actor", ""),
        "bill_refs": f.get("bill_refs", ""),
        "status": f.get("status", ""),
    }


def build_row(event, members):
    """members: list of (rid, fields) belonging to this event."""
    urls, outlets, parties = [], [], []
    for _, f in members:
        for line in (f.get("source_urls") or "").splitlines():
            if line.strip():
                urls.append(line.strip())
        if f.get("source"):
            outlets.append(f["source"])
        if f.get("party_source"):
            parties.append(f["party_source"])

    committee = next((f.get("committee") for _, f in members if f.get("committee")), "")
    chamber = next((f.get("chamber") for _, f in members if f.get("chamber")), "")
    # Majority + minority write-ups of one action merge to a neutral marker.
    party = parties[0] if len(set(parties)) == 1 else "majority"
    if len(set(parties)) > 1:
        party = "member" if "member" in parties else "majority"

    activity = event.get("activity_type")
    name = (event.get("name") or event.get("headline") or "").strip()
    return {
        "Name": f"{committee} — {name}"[:250],
        "event_id": event_id_for(urls),
        "headline": event.get("headline") or "",
        "summary": event.get("summary") or "",
        "why_it_matters": event.get("why_it_matters") or "",
        "date": event.get("date") or "",
        "committee": committee,
        "chamber": chamber,
        "party_source": party,
        "activity_type": activity if activity in cs.ACTIVITY_TYPE_CHOICES else None,
        "actor": (event.get("actor") or "")[:200],
        "bill_refs": (event.get("bill_refs") or "")[:200],
        "status": (event.get("status") or "")[:100],
        "source_urls": "\n".join(dict.fromkeys(urls)),
        "source_outlets": "\n".join(dict.fromkeys(outlets)),
        "article_count": len(members),
        "review_status": "unreviewed",
        "deduped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--all", action="store_true", help="every raw row, ignore the window")
    ap.add_argument("--clean-table", default=cs.EVENTS_TABLE)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    missing = [k for k, v in {"ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
                              "AIRTABLE_TOKEN": AIRTABLE_TOKEN,
                              "AIRTABLE_BASE_ID": AIRTABLE_BASE_ID}.items() if not v]
    if missing:
        sys.exit(f"Missing env vars: {', '.join(missing)}")

    api = Api(AIRTABLE_TOKEN)
    raw, raw_map = ensure_table(api, AIRTABLE_BASE_ID, cs.RAW_TABLE, cs.RAW_FIELDS)

    cutoff = "" if args.all else (
        datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat(timespec="seconds")
    ing_field = raw_map.get("ingested_at", "ingested_at")
    rows = [(r["id"], r["fields"]) for r in raw.all()
            if args.all or (r["fields"].get(ing_field) or "") >= cutoff]
    print(f"{len(rows)} raw rows in window ({'all' if args.all else f'{args.days}d by ingested_at'})")
    if not rows:
        print("Nothing to do.")
        return 0

    by_committee = {}
    for rid, f in rows:
        by_committee.setdefault(f.get("committee") or "unknown", []).append((rid, f))

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    members_by_id = {rid: f for rid, f in rows}

    # Cluster per committee; single-row committees skip the LLM call.
    multi = [(c, rs) for c, rs in by_committee.items() if len(rs) > 1]
    single = [(c, rs) for c, rs in by_committee.items() if len(rs) == 1]
    print(f"{len(multi)} committees need clustering, {len(single)} single-row")

    clustered = congress_llm.map_concurrent(
        lambda cr: cluster(client, cr[0], cr[1]), multi,
        workers=WORKERS, label="cluster")

    events = []
    for (committee, rs), got in zip(multi, clustered):
        assigned = set()
        for ev in (got or []):
            ids = [i for i in (ev.get("member_ids") or []) if i in members_by_id]
            if not ids:
                continue
            ev["_committee"] = committee
            events.append((ev, [(i, members_by_id[i]) for i in ids]))
            assigned.update(ids)
        # Safety net: a row the model dropped becomes its own event rather
        # than vanishing. Same guard as dedupe.py.
        for rid, f in rs:
            if rid not in assigned:
                ev = single_row_event(rid, f)
                ev["_committee"] = committee
                events.append((ev, [(rid, f)]))
    for committee, rs in single:
        rid, f = rs[0]
        ev = single_row_event(rid, f)
        ev["_committee"] = committee
        events.append((ev, [(rid, f)]))

    print(f"{len(rows)} rows -> {len(events)} events; classifying...")
    verdicts = congress_llm.map_concurrent(
        lambda e: classify_event(client, e[0]), events,
        workers=WORKERS, label="classify")

    out_rows = []
    for (ev, members), v in zip(events, verdicts):
        row = build_row(ev, members)
        comps = cs.valid((v or {}).get("competencies"), cs.COMPETENCY_CHOICES)
        rel = cs.clamp_relevance((v or {}).get("relevance"))
        row["competency"] = comps
        row["topic_tags"] = cs.valid((v or {}).get("topic_tags"), cs.TOPIC_TAG_CHOICES)
        row["relevance"] = rel if (comps and rel) else None
        out_rows.append(row)

    hit = sum(1 for r in out_rows if r["competency"])
    print(f"\n{hit}/{len(out_rows)} events matched a competency (RAF-relevant)\n")
    for r in sorted(out_rows, key=lambda x: (-(x.get("relevance") or 0), x["date"]), reverse=False):
        comp = ",".join(r["competency"]) or "none"
        tags = " ".join(f"#{t}" for t in r["topic_tags"][:3])
        print(f"  [{comp} {r.get('relevance') or '-'}] {r['date']} {r['committee']}: "
              f"{r['headline'][:66]} {tags}")

    if args.dry_run:
        print("\n(dry run — nothing written)")
        return 0

    clean, clean_map = ensure_table(api, AIRTABLE_BASE_ID, args.clean_table, cs.EVENT_FIELDS)
    created, updated = upsert(clean, clean_map, out_rows, "event_id",
                              preserve=cs.REVIEW_FIELDS)
    print(f"\nWrote {created} new, {updated} updated -> {args.clean_table}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
