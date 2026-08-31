#!/usr/bin/env python3
"""Federal executive-branch tracker — cluster + classify (clean layer).

Reads 'Federal Raw', clusters rows describing the same underlying action into
one EVENT, classifies each event against the federal executive-branch rubric,
and upserts into 'Federal Events'.

Clustering carries more weight here than on any other tracker. One OMB memo is
covered the same afternoon by FedScoop, Nextgov, Government Executive, Federal
News Network and The Hill, and the memo itself arrives separately from
whitehouse.gov and again as a Federal Register document. Five rows, one event —
and the merged event is strictly better than any single row, because the
primary-source lane supplies the instrument and the news lane supplies what it
actually means in practice.

Three deliberate differences from congress_dedupe.py:

1. **Grouping is by AGENCY, not by chamber.** Cross-source coverage of one
   action shares the agency the action belongs to; two different agencies almost
   never describe the same action. Rows with no agency group together, and any
   group over CHUNK rows is split so one clustering call never runs past the
   model's useful context.

2. **The lane is preserved from the highest-provenance member.** A cluster
   containing both an OMB memo and five news stories about it is an
   `executive-action`, not `news` — otherwise a primary-source instrument would
   be filed as press coverage. Same for `verification`: `official` beats
   `reported` beats `draft-leaked`.

3. **The window filters on `ingested_at`,** not on the action date, for the
   reason documented in congress_dedupe.py: an item ingested today about an
   action six weeks ago would otherwise fall outside every future window.

Usage:
    python federal_dedupe.py --days 21
    python federal_dedupe.py --all --dry-run          # reclassify everything
    python federal_dedupe.py --days 7 --clean-table "Federal Events2"
"""

import argparse
import hashlib
import os
import sys
from datetime import datetime, timedelta, timezone

from anthropic import Anthropic
from dotenv import load_dotenv
from pyairtable import Api

from tracker.federal import llm as federal_llm
from tracker.federal import schema as fs
from tracker.shared.airtable import ensure_table, upsert

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")

MODEL = federal_llm.MODEL_CLASSIFY
WORKERS = federal_llm.WORKERS
CHUNK = 50           # max rows per clustering call

# Highest provenance wins when a cluster spans lanes: the instrument outranks
# the coverage of the instrument.
# The instrument outranks the coverage of the instrument, and an instrument
# outranks a finding about it: if OPM issues guidance in response to a GAO
# report, the event is the guidance. Oversight sits above news because GAO
# publishing its own report is a primary source; trade coverage of it is not.
LANE_RANK = {"executive-action": 4, "rulemaking": 3, "oversight": 2, "news": 1}
VERIFICATION_RANK = {"official": 3, "reported": 2, "draft-leaked": 1}

CLUSTER_SYSTEM = f"""You deduplicate rows in a federal executive-branch activity tracker.

You receive rows about ONE agency (or one group of unattributed rows) over a
recent window. Multiple rows very often describe the SAME underlying action: the
agency's own release, the Federal Register document, the GAO report, and three or
four trade-press write-ups of it all arrive within a day or two. Cluster them into distinct EVENTS
and synthesize each.

Your job is clustering + synthesis ONLY. Do NOT judge which capacity an event
touches or how relevant it is — a separate classification step handles that.

Rules:
- Two rows belong to the same event only if they describe the same underlying
  action (the same memo, rule, directive, RIF, launch, award, report, or court
  order), not merely the same topic or the same agency. Two different OPM
  memos are two events even if both concern hiring.
- A primary-source row (the agency's own release, the Federal Register document,
  the GAO report itself) and news coverage of it are ONE event. A GAO report and
  a trade-press write-up of that report are ONE event, even when the write-up
  leads with a different number from the report's headline finding. Prefer the primary source's account of
  WHAT the instrument is, and use the coverage for what it does in practice and
  for context the agency omitted.
- A draft reported by the press and the same document later published officially
  are ONE event at its most advanced stage; note the progression in the summary.
- Where the primary source and the coverage disagree on significance, describe
  the mechanism and let the disagreement show. Do not adopt either framing.
- Strip promotional and partisan adjectives. Write what the instrument does.
- Every input row id must appear in exactly one event.
- A row that matches nothing is its own single-row event.

Output ONLY this JSON (no fences, no preamble):
{{
  "events": [
    {{
      "member_ids": ["rec...", "rec..."],
      "name": "concise neutral title of the action, 5-10 words, sentence case",
      "headline": "one neutral line: what happened, best synthesis of the rows",
      "summary": "2-3 plain sentences: the mechanism, and what it would actually do",
      "why_it_matters": "one line for a Recoding America reader, empty string if none",
      "date": "YYYY-MM-DD of the action (earliest credible)",
      "instrument_type": "one of: {' | '.join(fs.INSTRUMENT_TYPE_CHOICES)}",
      "instrument_id": "the document's identifier if any, e.g. 'M-26-15', else \\"\\"",
      "branch": "one of: {' | '.join(fs.BRANCH_CHOICES)}",
      "agency": ["agencies the action is by or about, from: {', '.join(fs.AGENCY_CHOICES)}"],
      "actor": "who acted",
      "document_url": "URL of the primary document if one of the rows names it, else \\"\\"",
      "status": "optional stage note, empty string if N/A"
    }}
  ]
}}
"""

CLASSIFY_SYSTEM = federal_llm.RUBRIC_SYSTEM + """

---

# Output for this task

You are given ONE federal executive-branch event. Classify it.

Output ONLY this JSON, no fences:
{ "competencies": ["digital", "incentives"], "relevance": 3, "topic_tags": ["it-modernization"] }

For a non-fit: { "competencies": [], "relevance": 0, "topic_tags": [] }
"""


def event_id_for(urls):
    """Stable id from the member source URLs, so the same cluster lands on the
    same row across runs and its review annotations survive."""
    joined = "\n".join(sorted(u for u in urls if u))
    return hashlib.sha1(joined.encode()).hexdigest()[:16]


def cluster(client, group, rows):
    payload = {
        "agency_group": group,
        "rows": [{
            "id": rid,
            "name": f.get("Name", ""),
            "headline": f.get("headline", ""),
            "notes": f.get("notes", ""),
            "date": f.get("date", ""),
            "lane": f.get("lane", ""),
            "source": f.get("source", ""),
            "instrument_type": f.get("instrument_type", ""),
            "instrument_id": f.get("instrument_id", ""),
            "verification": f.get("verification", ""),
            "url": (f.get("source_urls") or "").splitlines()[:1],
        } for rid, f in rows],
    }
    out = federal_llm.call(client, MODEL, CLUSTER_SYSTEM, payload, max_tokens=8000)
    return out.get("events") or []


def classify_event(client, event):
    return federal_llm.call(client, MODEL, CLASSIFY_SYSTEM, {
        "name": event.get("name", ""),
        "headline": event.get("headline", ""),
        "summary": event.get("summary", ""),
        "instrument_type": event.get("instrument_type", ""),
        "instrument_id": event.get("instrument_id", ""),
        "lane": event.get("_lane", ""),
        "branch": event.get("branch", ""),
        "agency": event.get("agency", []),
        "actor": event.get("actor", ""),
    }, max_tokens=600)


def single_row_event(rid, f):
    """A group with one row skips the clustering call — the same shortcut the
    other dedupe scripts take, and most of the volume here."""
    return {
        "member_ids": [rid],
        "name": (f.get("Name") or "").split(" — ", 1)[-1],
        "headline": f.get("headline", ""),
        "summary": f.get("notes", ""),
        "why_it_matters": "",
        "date": f.get("date", ""),
        "instrument_type": f.get("instrument_type", ""),
        "instrument_id": f.get("instrument_id", ""),
        "branch": f.get("branch", ""),
        "agency": f.get("agency", []) or [],
        "actor": f.get("actor", ""),
        "document_url": f.get("document_url", ""),
        "status": f.get("status", ""),
    }


def build_row(event, members):
    """members: list of (rid, fields) belonging to this event."""
    urls, outlets = [], []
    for _, f in members:
        for line in (f.get("source_urls") or "").splitlines():
            if line.strip():
                urls.append(line.strip())
        if f.get("source"):
            outlets.append(f["source"])

    # Provenance wins, not recency: see LANE_RANK.
    lane = max((f.get("lane") for _, f in members if f.get("lane")),
               key=lambda l: LANE_RANK.get(l, 0), default="news")
    verification = max((f.get("verification") for _, f in members if f.get("verification")),
                       key=lambda v: VERIFICATION_RANK.get(v, 0), default="reported")

    agencies = fs.valid(event.get("agency"), fs.AGENCY_CHOICES)
    if not agencies:
        for _, f in members:
            agencies = fs.valid(f.get("agency"), fs.AGENCY_CHOICES)
            if agencies:
                break

    instrument = event.get("instrument_type")
    if instrument not in fs.INSTRUMENT_TYPE_CHOICES:
        instrument = next((f.get("instrument_type") for _, f in members
                           if f.get("instrument_type") in fs.INSTRUMENT_TYPE_CHOICES), None)
    # A cluster's primary document must not be one of the cluster's own source
    # URLs: inheriting a member article's URL would present trade-press coverage
    # as the instrument, which is the one thing this column exists to prevent.
    url_set = set(urls)
    doc = next((d for d in [event.get("document_url")]
                + [f.get("document_url") for _, f in members]
                if d and d not in url_set), "")
    branch = event.get("branch")
    if branch not in fs.BRANCH_CHOICES:
        branch = next((f.get("branch") for _, f in members
                       if f.get("branch") in fs.BRANCH_CHOICES), "executive")

    name = (event.get("name") or event.get("headline") or "").strip()
    label = agencies[0] if agencies else lane
    return {
        "Name": f"{label} — {name}"[:250],
        "event_id": event_id_for(urls),
        "short_title": name[:120],
        "headline": event.get("headline") or "",
        "summary": event.get("summary") or "",
        "why_it_matters": event.get("why_it_matters") or "",
        "date": event.get("date") or "",
        "lane": lane,
        "branch": branch,
        "agency": agencies,
        "instrument_type": instrument,
        "instrument_id": (event.get("instrument_id") or next(
            (f.get("instrument_id") for _, f in members if f.get("instrument_id")), ""))[:120],
        "verification": verification,
        "actor": (event.get("actor") or "")[:200],
        "status": (event.get("status") or "")[:100],
        "document_url": (doc or "")[:500],
        "source_urls": "\n".join(dict.fromkeys(urls)),
        "source_outlets": "\n".join(dict.fromkeys(outlets)),
        "article_count": len(members),
        "review_status": "unreviewed",
        "deduped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def prune_orphans(clean, clean_map, produced_ids, processed_urls, dry_run=False):
    """Delete clean rows this run superseded.

    event_id hashes the member URLs, so re-clustering three rows into one mints
    a new id and leaves the originals behind; upsert alone never removes them.
    A row is only in scope if every one of its source URLs was among the raw
    rows we just processed — that means this run owned all of its inputs and is
    entitled to replace it. Reviewed rows are reported, never silently deleted.
    """
    id_f = clean_map.get("event_id", "event_id")
    url_f = clean_map.get("source_urls", "source_urls")
    status_f = clean_map.get("review_status", "review_status")
    notes_f = clean_map.get("reviewer_notes", "reviewer_notes")

    stale, reviewed = [], []
    for rec in clean.all():
        f = rec["fields"]
        eid = (f.get(id_f) or "").strip()
        if not eid or eid in produced_ids:
            continue
        urls = {u.strip() for u in (f.get(url_f) or "").splitlines() if u.strip()}
        if not urls or not urls <= processed_urls:
            continue
        if (f.get(status_f) or "unreviewed") != "unreviewed" or f.get(notes_f):
            reviewed.append((rec["id"], f))
            continue
        stale.append(rec["id"])

    if stale and not dry_run:
        for i in range(0, len(stale), 10):
            clean.batch_delete(stale[i:i + 10])
    for _, f in reviewed:
        print(f"  KEPT superseded but reviewed: {(f.get('headline') or '')[:70]}")
    return len(stale), len(reviewed)


# Agencies that describe the reporter rather than the subject. A GAO or IG
# report about FEMA's staffing is an event about FEMA — grouping it under `gao`
# would file every watchdog product together and cluster none of them with the
# coverage of the same finding.
REPORTER_AGENCIES = {"gao", "governmentwide", "courts", "other"}


def group_key(fields):
    """Agency the action belongs to, for clustering.

    Sorted, so the key does not depend on the order the model happened to list
    the agencies in — two outlets covering one GAO report on FEMA that returned
    ["gao","fema"] and ["fema","gao"] were landing in different groups and
    surviving as duplicate events. Reporter agencies are used only when nothing
    more specific is present.
    """
    agencies = sorted(fields.get("agency") or [])
    subject = [a for a in agencies if a not in REPORTER_AGENCIES]
    return (subject or agencies or ["(unattributed)"])[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--all", action="store_true", help="every raw row, ignore the window")
    ap.add_argument("--clean-table", default=fs.EVENTS_TABLE)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    missing = [k for k, v in {"ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
                              "AIRTABLE_TOKEN": AIRTABLE_TOKEN,
                              "AIRTABLE_BASE_ID": AIRTABLE_BASE_ID}.items() if not v]
    if missing:
        sys.exit(f"Missing env vars: {', '.join(missing)}")

    api = Api(AIRTABLE_TOKEN)
    raw, raw_map = ensure_table(api, AIRTABLE_BASE_ID, fs.RAW_TABLE, fs.RAW_FIELDS)

    cutoff = "" if args.all else (
        datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat(timespec="seconds")
    ing_field = raw_map.get("ingested_at", "ingested_at")
    rows = [(r["id"], r["fields"]) for r in raw.all()
            if args.all or (r["fields"].get(ing_field) or "") >= cutoff]
    print(f"{len(rows)} raw rows in window "
          f"({'all' if args.all else f'{args.days}d by ingested_at'})")
    if not rows:
        print("Nothing to do.")
        return 0

    by_group = {}
    for rid, f in rows:
        by_group.setdefault(group_key(f), []).append((rid, f))

    # Split oversized groups. The Hill plus five trade outlets on a busy
    # governmentwide week can push `governmentwide` past a comfortable
    # clustering call; chunking risks splitting a duplicate pair across two
    # calls, which is a smaller cost than a truncated response.
    groups = []
    for g, rs in by_group.items():
        if len(rs) <= CHUNK:
            groups.append((g, rs))
            continue
        for i in range(0, len(rs), CHUNK):
            groups.append((f"{g} [{i // CHUNK + 1}]", rs[i:i + CHUNK]))
        print(f"  split {g}: {len(rs)} rows -> {-(-len(rs) // CHUNK)} chunks")

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    members_by_id = {rid: f for rid, f in rows}

    multi = [(g, rs) for g, rs in groups if len(rs) > 1]
    single = [(g, rs) for g, rs in groups if len(rs) == 1]
    print(f"{len(multi)} groups need clustering, {len(single)} single-row")

    clustered = federal_llm.map_concurrent(
        lambda gr: cluster(client, gr[0], gr[1]), multi,
        workers=WORKERS, label="cluster")

    def tag(ev, members):
        """The classifier wants the lane the event will be filed under, which is
        the highest-provenance member's lane, not any one row's."""
        ev["_lane"] = max((f.get("lane") for _, f in members if f.get("lane")),
                          key=lambda l: LANE_RANK.get(l, 0), default="news")
        return ev

    events = []
    for (group, rs), got in zip(multi, clustered):
        assigned = set()
        for ev in (got or []):
            ids = [i for i in (ev.get("member_ids") or []) if i in members_by_id]
            if not ids:
                continue
            members = [(i, members_by_id[i]) for i in ids]
            events.append((tag(ev, members), members))
            assigned.update(ids)
        # Safety net: a row the model dropped becomes its own event rather than
        # vanishing. Same guard as the other dedupe scripts.
        for rid, f in rs:
            if rid not in assigned:
                events.append((tag(single_row_event(rid, f), [(rid, f)]), [(rid, f)]))
    for group, rs in single:
        rid, f = rs[0]
        events.append((tag(single_row_event(rid, f), [(rid, f)]), [(rid, f)]))

    print(f"{len(rows)} rows -> {len(events)} events; classifying...")
    verdicts = federal_llm.map_concurrent(
        lambda e: classify_event(client, e[0]), events,
        workers=WORKERS, label="classify")

    out_rows = []
    for (ev, members), v in zip(events, verdicts):
        row = build_row(ev, members)
        comps = fs.valid((v or {}).get("competencies"), fs.COMPETENCY_CHOICES)
        rel = fs.clamp_relevance((v or {}).get("relevance"))
        row["competency"] = comps
        row["topic_tags"] = fs.valid((v or {}).get("topic_tags"), fs.TOPIC_TAG_CHOICES)
        row["relevance"] = rel if (comps and rel) else None
        out_rows.append(row)

    hit = sum(1 for r in out_rows if r["competency"])
    merged = sum(1 for r in out_rows if r["article_count"] > 1)
    print(f"\n{hit}/{len(out_rows)} events matched a competency (RA-relevant); "
          f"{merged} events merged >1 source\n")
    for r in sorted(out_rows, key=lambda x: (x["date"], -(x.get("relevance") or 0))):
        comp = ",".join(r["competency"]) or "none"
        tags = " ".join(f"#{t}" for t in r["topic_tags"][:3])
        srcs = f" ({r['article_count']} srcs)" if r["article_count"] > 1 else ""
        print(f"  [{comp} {r.get('relevance') or '-'}] {r['date']} {r['lane']:16} "
              f"{r['headline'][:62]}{srcs} {tags}")

    if args.dry_run:
        print("\n(dry run — nothing written)")
        return 0

    clean, clean_map = ensure_table(api, AIRTABLE_BASE_ID, args.clean_table, fs.EVENT_FIELDS)
    created, updated = upsert(clean, clean_map, out_rows, "event_id",
                              preserve=fs.REVIEW_FIELDS)

    processed_urls = set()
    for _, f in rows:
        processed_urls.update(
            u.strip() for u in (f.get("source_urls") or "").splitlines() if u.strip())
    deleted, kept = prune_orphans(
        clean, clean_map, {r["event_id"] for r in out_rows}, processed_urls)

    print(f"\nWrote {created} new, {updated} updated, {deleted} superseded "
          f"removed -> {args.clean_table}")
    if kept:
        print(f"{kept} superseded row(s) kept because they carry review notes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
