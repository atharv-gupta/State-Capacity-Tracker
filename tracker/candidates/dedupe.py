#!/usr/bin/env python3
"""Gubernatorial Candidates Tracker — dedupe/condense stage (clean layer).

The candidate sibling of dedupe.py. candidates_pipeline.py writes one row per
ARTICLE to the raw 'Candidate Developments' table (a loose gate lets a lot of
near-duplicate campaign coverage through — five outlets on one Hobbs
announcement land as five rows). This stage reads the last N days of that raw
table, clusters rows that describe the SAME underlying development for ONE
candidate into a single DEVELOPMENT, and rebuilds that window of the clean
'Candidate Events' table: one row per development, all source URLs/outlets
merged, then authoritatively classified against rubrics/rubric.md by a stronger model.

Mirrors dedupe.py exactly in shape (cluster -> classify -> rebuild window). The
two differences from the main tracker: it clusters per CANDIDATE (not per
state), and the rubric is sent with a short candidate adaptation — for a
candidate, what they SAY or PLAN counts the same as an enacted action.

Runs weekly (Mondays), right after the wide candidates_pipeline.py scrape, the
same cadence as dedupe.py for the main tracker.

Usage:
    python candidates_dedupe.py                  # cluster the last 7 days
    python candidates_dedupe.py --days 30
    python candidates_dedupe.py --state CO
    python candidates_dedupe.py --dry-run        # show clusters, don't write
"""

import argparse
import concurrent.futures
import json
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

from anthropic import Anthropic
from dotenv import load_dotenv
from tracker.shared.wim import CANDIDATE_RULES
from pyairtable import Api

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")
if not all([ANTHROPIC_API_KEY, AIRTABLE_TOKEN, AIRTABLE_BASE_ID]):
    sys.exit("Missing env vars; see .env_example.")

RAW_TABLE = "Candidate Developments"
CLEAN_TABLE = "Candidate Events"
MODEL = "claude-sonnet-4-6"   # stronger model for synthesis + classification
WORKERS = 6

# rubrics/rubric.md is the same classification rubric the main dedupe uses; we send it as
# the cached system prompt, prefixed with a candidate adaptation (see classify).
from tracker.paths import RUBRICS

RUBRIC_PATH = os.path.join(RUBRICS, "rubric.md")
with open(RUBRIC_PATH, encoding="utf-8") as _fh:
    RUBRIC = _fh.read()

# The rubric is written for enacted government events. For a candidate, a stated
# plan/position/pledge counts exactly as an enacted action would, and direction
# is irrelevant (Principle 2). Prepended to RUBRIC so the cached suffix is stable.
CANDIDATE_ADAPTATION = """You are classifying a 2026 gubernatorial CANDIDATE'S
development (a plan, pledge, statement, interview answer, or an action taken in
a current office), not an enacted state-government action. Apply the rubric
below EXACTLY, with one adaptation: for a candidate, what they SAY or PLAN to do
counts the same as an enacted action — a promised day-one regulatory-reform EO
is a `procedure` example, a pledged IT-consolidation is a `digital` example.
Principle 1 (capacity, not subject matter) and Principle 2 (direction doesn't
matter) apply unchanged. A tax plan or a healthcare plan with no bearing on how
the state builds and runs itself is `none` — the common, correct outcome.

---

"""

COMPETENCY_CHOICES = ["civil-service", "procedure", "digital", "incentives"]
DEV_TYPE_CHOICES = [
    "policy-plan", "press-release", "speech-quote", "interview",
    "news-coverage", "official-action", "other",
]
# Same descriptive topic tags as the main clean Events table (dedupe.py).
TOPIC_TAG_CHOICES = [
    "it-modernization", "ai", "data-privacy", "cybersecurity", "broadband",
    "benefits-systems", "procurement", "occupational-licensing", "permitting",
    "housing-land-use", "regulatory-reform", "hiring-recruitment",
    "compensation-pensions", "labor-relations", "telework-rto", "layoffs-rif",
    "reorganization", "transparency", "study-commission",
    "data-center", "tax-incentives", "energy-utility", "health-human-services",
    "higher-ed", "k12-education", "child-welfare",
]

# Schema for the clean developments table. Field names must match
# build_clean_row's keys EXACTLY. Mirrors dedupe.py:CLEAN_FIELDS, plus the
# candidate-specific columns (candidate, dev_type, summary, quote) that the
# 'Governors 26' web tab already reads.
CLEAN_FIELDS = [
    {"name": "Name", "type": "singleLineText"},               # primary field
    {"name": "event_id", "type": "singleLineText"},
    {"name": "candidate", "type": "singleLineText"},
    {"name": "state", "type": "singleLineText"},
    {"name": "date", "type": "date", "options": {"dateFormat": {"name": "iso"}}},
    {"name": "dev_type", "type": "singleSelect",
     "options": {"choices": [{"name": d} for d in DEV_TYPE_CHOICES]}},
    {"name": "headline", "type": "multilineText"},
    {"name": "summary", "type": "multilineText"},
    {"name": "why_it_matters", "type": "multilineText"},
    {"name": "quote", "type": "multilineText"},
    {"name": "competency", "type": "multipleSelects",
     "options": {"choices": [{"name": c} for c in COMPETENCY_CHOICES]}},
    {"name": "relevance", "type": "number", "options": {"precision": 0}},
    {"name": "topic_tags", "type": "multipleSelects",
     "options": {"choices": [{"name": t} for t in TOPIC_TAG_CHOICES]}},
    {"name": "source_urls", "type": "multilineText"},
    {"name": "source_outlets", "type": "singleLineText"},
    {"name": "article_count", "type": "number", "options": {"precision": 0}},
    {"name": "Status", "type": "singleLineText"},
    {"name": "deduped_at", "type": "dateTime",
     "options": {"dateFormat": {"name": "iso"},
                 "timeFormat": {"name": "24hour"},
                 "timeZone": "utc"}},
]

SYSTEM_PROMPT = f"""You deduplicate rows in a 2026 gubernatorial candidates
tracker. You receive a list of articles (rows) about ONE candidate from the past
week. Multiple rows often describe the SAME underlying development — one policy
rollout, one speech, one office action — reported by different outlets or
rewritten across a news cycle. Cluster them into distinct DEVELOPMENTS and
synthesize each one.

Your job is clustering + synthesis ONLY. Do NOT judge which state-capacity
competency a development touches or how relevant it is — a separate
classification step handles that.

Rules:
- Two rows belong to the same development only if they describe the same
  underlying thing the candidate said, released, or did (same plan, same
  speech, same pledge, same office action) — not merely the same topic. Two
  separate speeches that both mention housing are TWO developments.
- Follow-up coverage, reactions, and re-reports of one announcement are the SAME
  development; fold them in and note any escalation in the summary.
- Every input row id must appear in exactly one development.
- A row that matches nothing is its own single-row development.

Output ONLY this JSON (no fences, no preamble):
{{
  "developments": [
    {{
      "member_ids": ["rec...", "rec..."],
      "name": "concise title of the development, 5-10 words, no candidate name, sentence case",
      "headline": "one plain sentence: what the candidate said/did, best synthesis of the member rows",
      "summary": "2-3 sentences of substance",
      "why_it_matters": "one line, written to the why_it_matters rules in the system prompt",
      "quote": "a short verbatim candidate quote if one carries the story, else \\"\\"",
      "dev_type": "one of: {' | '.join(DEV_TYPE_CHOICES)}",
      "date": "YYYY-MM-DD of the development (earliest credible)",
      "status": "optional short stage note, empty string if N/A"
    }}
  ]
}}""" + CANDIDATE_RULES


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


def cluster_candidate(client, candidate, rows):
    """rows: list of (record_id, fields). Returns the model's development list."""
    payload = [{
        "id": rid,
        "date": f.get("date", ""),
        "dev_type": f.get("dev_type", ""),
        "headline": f.get("headline", ""),
        "summary": f.get("summary", ""),
        "quote": f.get("quote", ""),
        "outlet": f.get("source_outlets", ""),
        "url": f.get("url") or f.get("source_urls", ""),
    } for rid, f in rows]
    resp = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user",
                   "content": json.dumps({"candidate": candidate, "rows": payload})}],
    )
    return parse_json_response(resp.content[0].text)["developments"]


def classify_development(client, candidate, state, ev):
    """Classify ONE synthesized development against rubrics/rubric.md (candidate-adapted).

    Returns {"competencies", "relevance", "topic_tags"}. rubrics/rubric.md (with the
    candidate-adaptation prefix) is the cached system prompt, identical across
    every call; the synthesized development goes in the user message. Runs over
    EVERY development — including single-article ones, which skip clustering."""
    payload = {
        "candidate": candidate,
        "state": state,
        "dev_type": ev.get("dev_type", ""),
        "name": ev.get("name", ""),
        "headline": ev.get("headline", ""),
        "summary": ev.get("summary", ""),
        "quote": ev.get("quote", ""),
    }
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=[{
            "type": "text",
            "text": CANDIDATE_ADAPTATION + RUBRIC,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": json.dumps(payload)}],
    )
    return parse_json_response(resp.content[0].text)


def build_clean_row(candidate, state, ev, members, deduped_at):
    urls, outlets = [], []
    for _, f in members:
        raw_urls = (f.get("source_urls") or "").splitlines() or [f.get("url", "")]
        for u in raw_urls:
            if u.strip() and u.strip() not in urls:
                urls.append(u.strip())
        o = (f.get("source_outlets") or "").strip()
        if o and o not in outlets:
            outlets.append(o)

    headline = (ev.get("headline") or ev.get("name") or "").strip()
    surname = candidate.split()[-1] if candidate else ""
    row = {
        "Name": f"{state} — {surname}: {headline}"[:255],
        "event_id": str(uuid.uuid4()),
        "candidate": candidate,
        "state": state,
        "headline": headline,
        "summary": (ev.get("summary") or "").strip(),
        "why_it_matters": (ev.get("why_it_matters") or "").strip(),
        "quote": (ev.get("quote") or "").strip(),
        "Status": (ev.get("status") or "").strip(),
        "source_urls": "\n".join(urls),
        "source_outlets": ", ".join(outlets),
        "article_count": len(members),
        "deduped_at": deduped_at,
    }

    dev_type = ev.get("dev_type", "")
    row["dev_type"] = dev_type if dev_type in DEV_TYPE_CHOICES else "other"

    # Classification (attached to ev by classify_development before this call).
    comps = ev.get("competencies") or []
    if isinstance(comps, str):
        comps = [comps]
    comps = [c for c in comps if c in COMPETENCY_CHOICES]
    if comps:
        row["competency"] = comps
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

    return row


def ensure_clean_table(base, table_name):
    """Return the clean Table, creating it (with CLEAN_FIELDS) if it does not
    exist, or adding any missing columns if it does. Same shape as
    dedupe.py:ensure_clean_table."""
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


def single_row_development(rid, f):
    """A raw row that clusters with nothing becomes its own development, carrying
    its raw fields straight through (the clustering call is skipped)."""
    return {
        "member_ids": [rid],
        "name": (f.get("headline") or "").strip(),
        "headline": (f.get("headline") or "").strip(),
        "summary": (f.get("summary") or "").strip(),
        "why_it_matters": (f.get("why_it_matters") or "").strip(),
        "quote": (f.get("quote") or "").strip(),
        "dev_type": f.get("dev_type", ""),
        "date": f.get("date", ""),
        "status": (f.get("Status") or f.get("status") or "").strip(),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=7, help="window in days (default 7)")
    ap.add_argument("--all", action="store_true",
                    help="process every raw row, ignoring the date window")
    ap.add_argument("--state", default="", help="only this postal code")
    ap.add_argument("--clean-table", default=CLEAN_TABLE,
                    help=f"clean table to (re)build (default {CLEAN_TABLE!r})")
    ap.add_argument("--dry-run", action="store_true", help="show clusters, don't write")
    args = ap.parse_args()

    min_date = "" if args.all else (date.today() - timedelta(days=args.days)).isoformat()
    state_filter = args.state.upper()
    deduped_at = datetime.now(timezone.utc).isoformat()

    api = Api(AIRTABLE_TOKEN)
    base = api.base(AIRTABLE_BASE_ID)
    schema = base.schema()
    raw = base.table(next(t.id for t in schema.tables if t.name == RAW_TABLE))

    # Window on ingested_at, not date. `date` is the article's publication
    # date, so a development ingested today about a three-week-old action fell
    # outside every future window and was never clustered — 16 rows were lost
    # permanently that way. congress/dedupe.py already windows on ingested_at.
    #
    # But widening the raw selection alone would break the clean-table rebuild
    # below: a row published outside the window produces a clean row dated
    # outside it, which the clear step would miss, duplicating on the next run.
    # So derive the rebuild floor from what we actually selected, then re-select
    # every raw row at or after that floor. The superset guarantees that
    # everything the clear step deletes is rebuilt.
    all_raw = [(r["id"], r["fields"]) for r in raw.all()]

    def when_ingested(f):
        return (f.get("ingested_at") or f.get("date") or "")[:10]

    if args.all:
        rebuild_from = ""
    else:
        fresh = [f for _, f in all_raw if when_ingested(f) >= min_date]
        dates = [(f.get("date") or "")[:10] for f in fresh if f.get("date")]
        # Never narrower than the plain date window, so behaviour is unchanged
        # when nothing arrived late.
        rebuild_from = min(dates + [min_date]) if dates else min_date

    rows = []
    for rid, f in all_raw:
        if (f.get("date") or "") < rebuild_from:
            continue
        if state_filter and (f.get("state") or "").upper() != state_filter:
            continue
        rows.append((rid, f))
    scope = (" (all)" if args.all else
             f" since {rebuild_from}"
             + (f" (widened from {min_date} for late-ingested rows)"
                if rebuild_from < min_date else ""))
    print(f"{len(rows)} raw rows{scope}"
          + (f" in {state_filter}" if state_filter else ""))
    if not rows:
        return

    # Cluster per candidate (the natural unit — a candidate's articles about one
    # development cluster together), keyed with state to stay unambiguous.
    by_candidate = {}
    for rid, f in rows:
        key = ((f.get("state") or "??").upper(), (f.get("candidate") or "??"))
        by_candidate.setdefault(key, []).append((rid, f))

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    all_devs, errors = [], []

    def work(item):
        (state, candidate), crows = item
        if len(crows) == 1:
            rid, f = crows[0]
            return state, candidate, [single_row_development(rid, f)], crows
        return state, candidate, cluster_candidate(client, candidate, crows), crows

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(work, item): item[0] for item in by_candidate.items()}
        for fut in concurrent.futures.as_completed(futs):
            state, candidate = futs[fut]
            try:
                state, candidate, devs, crows = fut.result()
            except Exception as e:
                errors.append(f"{candidate}: {e}")
                print(f"  ERROR {candidate} — {e}")
                continue
            by_id = dict(crows)
            ids_seen = set()
            for ev in devs:
                members = [(rid, by_id[rid]) for rid in ev.get("member_ids", []) if rid in by_id]
                if not members:
                    continue
                ids_seen.update(rid for rid, _ in members)
                all_devs.append((state, candidate, ev, members))
            for rid in (r for r in by_id if r not in ids_seen):   # model missed a row
                all_devs.append((state, candidate,
                                 single_row_development(rid, by_id[rid]), [(rid, by_id[rid])]))
            merged = sum(1 for ev in devs if len(ev.get("member_ids", [])) > 1)
            print(f"  {state} {candidate}: {len(crows)} articles -> "
                  f"{len(devs)} developments" + (f" ({merged} merged)" if merged else ""))

    print(f"\n{len(rows)} raw articles -> {len(all_devs)} developments")

    # Classify every development against rubrics/rubric.md — single-article ones included.
    def classify_one(quad):
        state, candidate, ev, _members = quad
        try:
            result = classify_development(client, candidate, state, ev)
        except Exception as e:
            errors.append(f"classify {candidate}: {e}")
            print(f"  ERROR classifying {candidate} — {e}")
            result = {}
        comps = result.get("competencies") or []
        ev["competencies"] = comps if isinstance(comps, list) else [comps]
        ev["relevance"] = result.get("relevance") or 0
        tags = result.get("topic_tags") or []
        ev["topic_tags"] = tags if isinstance(tags, list) else [tags]

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(classify_one, all_devs))
    print(f"Classified {len(all_devs)} developments against rubrics/rubric.md")

    if args.dry_run:
        for state, candidate, ev, members in sorted(
                all_devs, key=lambda x: (x[0], x[1], x[2].get("date", ""))):
            tag = f"x{len(members)}" if len(members) > 1 else "  "
            comp = "+".join(ev.get("competencies", [])) or "none"
            rel = ev.get("relevance") or ""
            label = f"[{comp}{(' ' + str(rel)) if rel else ''}]"
            surname = candidate.split()[-1] if candidate else "?"
            print(f"  {state} {ev.get('date','??')} {tag} {surname:<12} {label:>22} "
                  f"{ev.get('headline','')[:60]}")
        n_rel = sum(1 for _, _, ev, _ in all_devs if ev.get("competencies"))
        print(f"\n{n_rel}/{len(all_devs)} developments matched a competency (RA-relevant)")
        return

    # Rebuild the clean table's window: delete clean rows in range, write fresh.
    # A --state run only clears its own state's window (rows dated in range, or
    # undated — those are always rewritten); a full run clears the whole window.
    clean = ensure_clean_table(base, args.clean_table)

    def in_window(f):
        d = f.get("date") or ""
        return d >= rebuild_from or not d

    stale = [r["id"] for r in clean.all()
             if in_window(r["fields"])
             and (not state_filter
                  or (r["fields"].get("state") or "").upper() == state_filter)]
    if stale:
        clean.batch_delete(stale)
        print(f"Cleared {len(stale)} stale clean rows in window")

    created = 0
    for state, candidate, ev, members in all_devs:
        try:
            clean.create(build_clean_row(candidate, state, ev, members, deduped_at),
                         typecast=True)
            created += 1
        except Exception as e:
            errors.append(f"write {candidate}: {e}")
            print(f"  ERROR writing {candidate} — {e}")
    print(f"Wrote {created} developments to '{args.clean_table}'")

    if errors:
        print("\n--- ERRORS ---")
        for e in errors:
            print(f"  {e}")


if __name__ == "__main__":
    main()
