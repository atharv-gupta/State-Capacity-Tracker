#!/usr/bin/env python3
"""State Capacity Tracker — dedupe/condense stage (clean layer).

Reads the last N days of 'Raw Events' (one row per article), clusters rows
that describe the same underlying government action into a single EVENT
(one government action shows up across many outlets — docs/SPEC.md §4 principle 1),
and upserts them into the clean 'Events' table: one row per event with all
source URLs/outlets merged.

Two things here used to differ from congress/dedupe.py and no longer do, both
of which had to change before this could run daily rather than on Mondays:

1. The window filters on `ingested_at`, not `date`. `date` is when the
   government acted, which the Haiku gate backdates to the action itself — so
   an article scraped today about a six-week-old action landed outside every
   future window and never clustered at all.

2. This upserts on a stable `event_id` instead of deleting the window and
   rewriting it. Delete-and-rewrite was survivable weekly; daily it would mint
   a new record id for every event in the trailing week every single day, and
   leave a human's verdict nowhere durable to live.

An event is written ONCE and then only accretes sources. `event_id` is minted
at first sighting and never changes. On later runs a cluster is matched to an
existing event by SOURCE URL OVERLAP, not by re-hashing its URL set — the set
grows as more outlets cover the same action, so a hash of it would change and
mint a duplicate. A matched event has its provenance updated (`source_urls`,
`source_outlets`, `source_type`, `article_count`) and everything in
FROZEN_FIELDS left exactly as first written; it costs no classify call.

The consequence worth knowing: an event first seen through one thin article
keeps that article's headline, summary, why_it_matters and competency even
after five more outlets cover it. That is deliberate — it buys a table that
stops changing under readers. `--reclassify` regenerates the frozen fields for
events already in the table (for a rubrics/rubric.md edit), without changing
any event_id.

Two windows, not one. `--days` is the TRIGGER window: it decides which states
have an article we have not seen and therefore need a model call at all.
`--context-days` is the CLUSTERING window, and is wider. A state that gets a
call is clustered against everything it has ingested in the context window, not
just the trigger window, so a late article can be grouped with siblings that
have already aged out and attach to their event instead of minting a duplicate
of it. Without that a straggler shares no URL with anything stored and always
looks new. The wider set costs nothing extra for quiet states — they are still
skipped before any call.

Usage:
    python dedupe.py                # cluster the last 7 days
    python dedupe.py --days 14
    python dedupe.py --dry-run      # show clusters, don't touch Airtable
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import sys
from datetime import date, timedelta

from anthropic import Anthropic
from dotenv import load_dotenv
from tracker.shared.airtable import ensure_table, upsert
from tracker.shared.wim import RULES
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

REVIEW_STATUS_CHOICES = ["unreviewed", "approved", "rejected", "needs-edit"]
REVIEW_FIELDS = ("review_status", "reviewer_notes")

# Written when the event is first created and never regenerated. Everything
# here comes from an LLM call (the clustering synthesis or the rubric classify),
# and re-deriving it daily made the same event reword itself under readers:
# measured over two consecutive runs, `headline` moved on 16 of 17 events whose
# state had more than one article that day and `why_it_matters` on 17 of 17.
# The remaining fields — source_urls / source_outlets / source_type /
# article_count — are the accreting ones, recomputed from members every run.
FROZEN_FIELDS = (
    "Name", "Notes", "date", "headline", "why_it_matters", "gov_actor",
    "activity_type", "actor_type", "Status",
    "competency", "relevance", "topic_tags",
)

# Schema for the clean events table, passed to shared.airtable.ensure_table,
# which creates a fresh table (e.g. Events2 via --clean-table) or adds missing
# columns to an existing one and returns a name_map. build_event_row's keys are
# these canonical names; the map resolves them to the real Airtable columns, so
# a pre-existing column differing only in case still matches.
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
    # `preserve` in shared.airtable.upsert holds these two back, so a nightly
    # run never clobbers what a reviewer typed. They were impossible before:
    # the window was deleted and rewritten, so a verdict had nowhere to live.
    # Mirrors congress/schema.py REVIEW_FIELDS.
    {"name": "review_status", "type": "singleSelect",
     "options": {"choices": [{"name": c} for c in REVIEW_STATUS_CHOICES]}},
    {"name": "reviewer_notes", "type": "multilineText"},
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
      "why_it_matters": "one line, MAX 30 WORDS, written to the why_it_matters rules in the system prompt",
      "status": "optional: introduced | enacted | etc., empty string if N/A"
    }}
  ]
}}""" + RULES


# Synthesis for a set of articles a HUMAN has already decided are one event.
# cluster_state can't be reused for that: its whole job is to decide grouping,
# so it may split the set back apart. Same field contract, one event asserted.
MERGE_PROMPT = f"""You write one entry in a state-government activity tracker.

You receive articles that ALL describe the SAME single government action. That
grouping is already decided and is not yours to revisit — do not split them,
do not drop any, do not hedge about whether they belong together.

Synthesize ONE event from all of them. Where they cover different procedural
stages of the same action (introduced, passed, signed), describe it at its
LATEST stage and note the progression in the notes. Weight the substance by
what the articles actually cover: if most of them are about one specific
measure, that measure is the headline, not a broader roundup that happens to
mention it.

Your job is synthesis ONLY. Do NOT judge which capacity it touches or how
significant it is — a separate classification step handles that.

Output ONLY this JSON (no fences, no preamble):
{{
  "name": "concise title of the action, 5-10 words, no state name, sentence case",
  "headline": "one-line what happened, best synthesis of ALL the articles",
  "notes": "1-2 plain sentences: what happened and why it matters for state capacity",
  "date": "YYYY-MM-DD of the government action at its latest stage",
  "activity_type": "one of: {' | '.join(ACTIVITY_TYPE_CHOICES)}",
  "gov_actor": "which body/office acted",
  "actor_type": "one of: {' | '.join(ACTOR_TYPE_CHOICES)}",
  "why_it_matters": "one line, MAX 30 WORDS, written to the why_it_matters rules in the system prompt",
  "status": "optional: introduced | enacted | etc., empty string if N/A"
}}""" + RULES


def synthesize_one(client, state, rows):
    """Re-synthesize ONE event from raw rows a human has merged.

    Used by tools/collapse_state_events.py, not by the daily run: regenerating
    text is exactly what the daily path refuses to do (see the module
    docstring), and is correct only when a person has asked for it.
    """
    payload = [{
        "date": f.get("date", ""),
        "headline": f.get("headline", ""),
        "gov_actor": f.get("gov_actor", ""),
        "activity_type": f.get("activity_type", ""),
        "actor_type": f.get("actor_type", ""),
        "notes": f.get("Notes", ""),
        "status": f.get("Status") or f.get("status", ""),
        "outlet": f.get("source_outlets", ""),
        "url": f.get("source_urls", ""),
    } for _, f in rows]
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=[{"type": "text", "text": MERGE_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user",
                   "content": json.dumps({"state": state, "articles": payload})}],
    )
    return parse_json_response(resp.content[0].text)


def parse_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    start = text.find("{")
    end = text.rfind("}")
    blob = text[start:end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        # The model occasionally emits two JSON objects back to back. Slicing
        # first-brace-to-last-brace then spans both and json.loads reports
        # "Extra data". Take the first complete object instead — silently
        # losing a classification is worse than using the first answer.
        obj, _ = json.JSONDecoder().raw_decode(blob)
        return obj


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


def event_id_for(urls):
    """Mint an id from the source URLs an event was FIRST seen with.

    Only ever called when creating a new event, never to look one up — see the
    module docstring. Deterministic rather than uuid4 so the same first sighting
    reproduces the same id, which makes a re-run of a fresh table idempotent.
    """
    joined = "\n".join(sorted(u for u in urls if u))
    return hashlib.sha1(joined.encode()).hexdigest()[:16]


def split_urls(text):
    return [u.strip() for u in (text or "").splitlines() if u.strip()]


def member_provenance(members):
    """The accreting half of an event row: which articles it is built from.
    Recomputed on every run, unlike FROZEN_FIELDS."""
    urls, outlets, types = [], [], []
    for _, f in members:
        for u in split_urls(f.get("source_urls")):
            if u not in urls:
                urls.append(u)
        o = f.get("source_outlets", "")
        if o and o not in outlets:
            outlets.append(o)
        st = f.get("source_type", "")
        if st and st not in types:
            types.append(st)
    return urls, outlets, types


def build_accretion_row(event_id, urls, outlets, types):
    """The row written for an event that ALREADY EXISTS: provenance only.

    Every FROZEN_FIELDS key is absent, and `upsert` PATCHes only the keys it is
    given, so the stored headline / summary / why_it_matters / competency are
    left untouched. If no new article joined, this is byte-identical to what is
    stored and `upsert` skips the write entirely.
    """
    return {
        "event_id": event_id,
        "source_urls": "\n".join(urls),
        "source_outlets": ", ".join(outlets),
        "source_type": ", ".join(types),
        "article_count": len(urls),
    }


def build_event_row(state, ev, members, event_id, provenance=None):
    """The full row written when an event is created (or --reclassify)."""
    urls, outlets, types = provenance or member_provenance(members)

    row = {
        "Name": f"{state} — {(ev.get('name') or ev.get('headline', '')).strip()}",
        "Notes": (ev.get("notes") or "").strip(),
        "event_id": event_id,
        "state": state,
        "headline": ev.get("headline", ""),
        "gov_actor": ev.get("gov_actor", ""),
        "why_it_matters": ev.get("why_it_matters", ""),
        "Status": ev.get("status", ""),
        "source_urls": "\n".join(urls),
        "source_outlets": ", ".join(outlets),
        "source_type": ", ".join(types),
        "article_count": len(urls),
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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=7,
                    help="TRIGGER window in days (default 7): how far back to "
                         "look for articles we have not seen yet")
    ap.add_argument("--context-days", type=int, default=30,
                    help="CLUSTERING window in days (default 30): how much of a "
                         "state's history to cluster against once it has "
                         "something new. Lets a late article join siblings that "
                         "have aged out of --days instead of duplicating their "
                         "event. Never narrower than --days.")
    ap.add_argument("--all", action="store_true",
                    help="process every raw row, ignoring the date window")
    ap.add_argument("--clean-table", default=CLEAN_TABLE,
                    help=f"clean table to (re)build (default {CLEAN_TABLE!r})")
    ap.add_argument("--dry-run", action="store_true", help="show clusters, don't write")
    ap.add_argument("--reclassify", action="store_true",
                    help="regenerate the frozen fields (headline, summary, "
                         "why_it_matters, competency) on events already in the "
                         "table. For a rubrics/rubric.md edit. event_ids are "
                         "never changed.")
    args = ap.parse_args()

    min_date = "" if args.all else (date.today() - timedelta(days=args.days)).isoformat()
    ctx_days = max(args.context_days, args.days)
    ctx_date = "" if args.all else (date.today() - timedelta(days=ctx_days)).isoformat()

    api = Api(AIRTABLE_TOKEN)
    base = api.base(AIRTABLE_BASE_ID)
    schema = base.schema()
    raw = base.table(next(t.id for t in schema.tables if t.name == RAW_TABLE))

    # Window on ingested_at, not date. `date` is when the government acted —
    # the Haiku gate backdates it to the action itself — so an article scraped
    # today about a six-week-old action carried a six-week-old date, fell
    # outside every future window and was never promoted at all. Measured on
    # the 428-row table when this changed (2026-09-02): 56 rows (13%) had an
    # ingest lag over 7 days and were unreachable by the old window.
    #
    # Rows written before the field existed have none; fall back to `date` so
    # a backfilled table and a partly-backfilled one both behave sanely.
    #
    # Unlike candidates/dedupe.py this needs no widened rebuild floor. That
    # dance exists to stop a date-keyed *clear* step from missing rows and
    # duplicating them; nothing here clears anything, and a cluster is matched
    # to an existing event by source-URL overlap, so a wider selection can only
    # ever land back on the same row.
    def when_ingested(f):
        return (f.get("ingested_at") or f.get("date") or "")[:10]

    all_raw = [(r["id"], r["fields"]) for r in raw.all()]
    rows = [x for x in all_raw if when_ingested(x[1]) >= min_date]
    ctx_rows = [x for x in all_raw if when_ingested(x[1]) >= ctx_date]
    print(f"{len(rows)} raw rows"
          + (" (all)" if args.all else f" ingested since {min_date}")
          + (f"; {len(ctx_rows)} in the {ctx_days}d clustering context"
             if not args.all and len(ctx_rows) != len(rows) else ""))
    if not rows:
        return

    # Load the clean table BEFORE clustering: which URLs are already spoken for
    # decides both which states need an LLM call at all and, later, whether a
    # cluster is a new event or more sources for an existing one.
    clean, clean_map = ensure_table(api, AIRTABLE_BASE_ID, args.clean_table,
                                    CLEAN_FIELDS)
    id_f = clean_map.get("event_id", "event_id")
    url_f = clean_map.get("source_urls", "source_urls")
    outlet_f = clean_map.get("source_outlets", "source_outlets")
    stype_f = clean_map.get("source_type", "source_type")

    known, url_owner = {}, {}
    for rec in clean.all():
        f = rec["fields"]
        eid = (f.get(id_f) or "").strip()
        if not eid:
            continue
        us = split_urls(f.get(url_f))
        known[eid] = {
            "urls": us,
            "outlets": [o.strip() for o in (f.get(outlet_f) or "").split(",") if o.strip()],
            "types": [t.strip() for t in (f.get(stype_f) or "").split(",") if t.strip()],
            "headline": f.get(clean_map.get("headline", "headline")) or "",
            "date": f.get(clean_map.get("date", "date")) or "",
        }
        for u in us:
            url_owner.setdefault(u, eid)
    print(f"{len(known)} existing events in '{args.clean_table}' "
          f"covering {len(url_owner)} source URLs")

    trigger_by_state, ctx_by_state = {}, {}
    for rid, f in rows:
        trigger_by_state.setdefault(f.get("state", "??"), []).append((rid, f))
    for rid, f in ctx_rows:
        ctx_by_state.setdefault(f.get("state", "??"), []).append((rid, f))

    # A state whose every TRIGGER-window article is already attached to an event
    # has nothing to say: skip it and spend no tokens. This is most states on
    # most days, and it is the bulk of the saving from not regenerating.
    #
    # A state that does have something new is clustered against its whole
    # CONTEXT window, so a late article meets the siblings it belongs with.
    quiet, widened = [], 0
    by_state = {}
    for st, srows in trigger_by_state.items():
        has_new = any(u not in url_owner
                      for _, f in srows for u in split_urls(f.get("source_urls")))
        if not has_new and not args.reclassify:
            quiet.append(st)
            continue
        ctx = ctx_by_state.get(st, srows)
        if len(ctx) > len(srows):
            widened += 1
        by_state[st] = ctx
    if quiet:
        print(f"{len(quiet)} state(s) had no unseen article, skipped: "
              f"{', '.join(sorted(quiet))}")
    if widened:
        print(f"{widened} active state(s) clustered against their {ctx_days}d "
              f"history so late articles can join an existing event")
    if not by_state:
        print("Nothing new to cluster.")
        return

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

    n_clustered = sum(len(v) for v in by_state.values())
    print(f"\n{n_clustered} raw articles clustered -> {len(all_events)} clusters")

    # Match each cluster to an existing event by SOURCE URL OVERLAP. A cluster
    # sharing no URL with anything stored is a new event; one that does is more
    # coverage of an event we already wrote, and only its provenance changes.
    def union(a, b):
        out = list(a)
        for x in b:
            if x not in out:
                out.append(x)
        return out

    plan, ambiguous = [], []
    for state, ev, members in all_events:
        urls, outlets, types = member_provenance(members)
        owners = list(dict.fromkeys(
            o for o in (url_owner.get(u) for u in urls) if o))
        item = {"state": state, "ev": ev, "members": members, "urls": urls,
                "outlets": outlets, "types": types}
        if owners:
            # Normally exactly one. More than one means this run's clustering
            # spans events that were written separately — merging them would
            # mean picking whose frozen text survives, so attach the new
            # article to ONE of them and report the rest rather than deciding.
            #
            # Attach to whichever came FIRST, ties broken by shared sources. A
            # later article about an action already recorded is not a new
            # judgment about it, so it nests under the original rather than
            # pulling the event forward into a fresh one.
            item["event_id"] = min(
                owners, key=lambda e: (known[e]["date"] or "9999-99-99",
                                       -len(set(urls) & set(known[e]["urls"]))))
            item["kind"] = "existing"
            if len(owners) > 1:
                ambiguous.append((state, owners, ev.get("headline", "")))
        else:
            item["event_id"] = event_id_for(urls)
            item["kind"] = "new"
        plan.append(item)

    n_new = sum(1 for p in plan if p["kind"] == "new")
    n_exist = len(plan) - n_new
    print(f"{n_new} new event(s), {n_exist} already known")

    # Classify ONLY what we are actually going to write text for. This is the
    # call the old code made for every event on every run.
    def classify_one(item):
        try:
            result = classify_event(client, item["ev"])
        except Exception as e:
            errors.append(f"classify {item['state']}: {e}")
            print(f"  ERROR classifying {item['state']} — {e}")
            result = {}
        ev = item["ev"]
        comps = result.get("competencies") or []
        ev["competencies"] = comps if isinstance(comps, list) else [comps]
        ev["relevance"] = result.get("relevance") or 0
        tags = result.get("topic_tags") or []
        ev["topic_tags"] = tags if isinstance(tags, list) else [tags]

    to_classify = [p for p in plan if p["kind"] == "new" or args.reclassify]
    if to_classify:
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            list(ex.map(classify_one, to_classify))
    print(f"Classified {len(to_classify)} event(s) against rubrics/rubric.md"
          + (f"; {len(plan) - len(to_classify)} kept their stored classification"
             if len(to_classify) < len(plan) else ""))

    if args.dry_run:
        for p in sorted(plan, key=lambda p: (p["state"], p["ev"].get("date", ""))):
            ev, state = p["ev"], p["state"]
            fresh = p["kind"] == "new" or args.reclassify
            mark = "NEW " if p["kind"] == "new" else "+src"
            if p["kind"] == "existing":
                added = len(set(p["urls"]) - set(known[p["event_id"]]["urls"]))
                if not added:
                    mark = "same"
            label = "(stored)"
            if fresh:
                comp = "+".join(ev.get("competencies", [])) or "none"
                rel = ev.get("relevance") or ""
                label = f"[{comp}{(' ' + str(rel)) if rel else ''}]"
            head = (ev.get("headline") or "") if fresh else \
                known[p["event_id"]]["headline"]
            print(f"  {mark} {state} {ev.get('date','??')} {label:>22} {head[:64]}")
        print("\n(dry run — nothing written)")
        return

    # Build rows. A new event gets everything; an existing one gets provenance
    # only, so `upsert`'s PATCH leaves every FROZEN_FIELDS value untouched.
    # Nothing is ever deleted here: under first-writer-wins an event is never
    # superseded by re-clustering, so there are no orphans to prune.
    out_rows, grew = [], 0
    for p in plan:
        eid = p["event_id"]
        if p["kind"] == "new":
            out_rows.append(build_event_row(p["state"], p["ev"], p["members"], eid,
                                            (p["urls"], p["outlets"], p["types"])))
            continue
        st = known[eid]
        prov = (union(st["urls"], p["urls"]),
                union(st["outlets"], p["outlets"]),
                union(st["types"], p["types"]))
        if len(prov[0]) > len(st["urls"]):
            grew += 1
        if args.reclassify:
            out_rows.append(build_event_row(p["state"], p["ev"], p["members"],
                                            eid, prov))
        else:
            out_rows.append(build_accretion_row(eid, *prov))

    created = updated = 0
    try:
        created, updated = upsert(clean, clean_map, out_rows, "event_id",
                                  preserve=REVIEW_FIELDS)
    except Exception as e:
        errors.append(f"upsert into {args.clean_table}: {e}")
        print(f"  ERROR upserting — {e}")

    print(f"Wrote {created} new, {updated} updated "
          f"({grew} gained a source) -> '{args.clean_table}'")
    if ambiguous:
        print(f"\n{len(ambiguous)} cluster(s) spanned more than one existing event. "
              f"Left as they are — merging would overwrite frozen text:")
        for state, owners, head in ambiguous:
            print(f"  {state} {head[:56]}  ({', '.join(owners)})")

    if errors:
        print("\n--- ERRORS ---")
        for e in errors:
            print(f"  {e}")


if __name__ == "__main__":
    main()
