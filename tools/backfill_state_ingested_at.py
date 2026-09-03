#!/usr/bin/env python3
"""One-time migration for the state tracker, to be run once before the first
daily dedupe. Idempotent — re-running it is a no-op.

Two jobs, both derivable from data already in Airtable, so neither costs an
LLM call:

1. 'Raw Events'.ingested_at — filled from each record's Airtable `createdTime`,
   which IS the moment the pipeline wrote the row, i.e. exactly the value the
   field would have had. Rows that somehow lack one fall back to `date`.

2. 'Events'.event_id — rewritten from the row's own source_urls with
   dedupe.event_id_for. Existing rows carry a uuid4 minted fresh on every run of
   the old code. The dedupe now matches events by source-URL OVERLAP rather than
   by id, so a uuid4 would in fact still work as an opaque identity; this step
   is cosmetic, and exists so that ids are reproducible from the sources an
   event was first seen with rather than being random per run.

   It only ever touches a legacy uuid4 or a blank. An id that is already minted
   is left alone, always: the id comes from the sources an event was FIRST seen
   with, and that set grows as more outlets cover the action, so recomputing it
   from the current sources would change a live event's id and split it from its
   own history.

3. 'Events' duplicates sharing one event_id — collapsed to a single row. This
   one is NOT cosmetic. They are fossils of the delete-and-rewrite path: it
   cleared rows whose `date` fell in the window and rewrote them, so a row the
   clusterer re-dated *out* of the window survived the clear and got a twin. One
   confirmed pair, same single URL, dated 07-11 and 07-13 and written a week
   apart. Two rows sharing an id breaks the upsert index, which keeps only one
   of them, so the other can never be updated again.

Usage:
    python -m tools.backfill_state_ingested_at --dry-run
    python -m tools.backfill_state_ingested_at
"""

import argparse
import os
import re
import sys
import time

from dotenv import load_dotenv
from pyairtable import Api

from tracker.shared.airtable import ensure_table
from tracker.state import dedupe, pipeline

load_dotenv()

AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")
if not all([AIRTABLE_TOKEN, AIRTABLE_BASE_ID]):
    sys.exit("Missing env vars; see .env_example.")

RAW_TABLE = "Raw Events"

# A minted event_id: 16 lowercase hex chars, from dedupe.event_id_for.
MINTED_ID = re.compile(r"^[0-9a-f]{16}$")


def batch_update(table, updates, dry_run):
    """Write in Airtable's 10-per-request batches, politely."""
    if dry_run:
        return
    for i in range(0, len(updates), 10):
        table.batch_update(updates[i:i + 10], typecast=True)
        time.sleep(0.2)


def backfill_ingested_at(api, dry_run):
    table, name_map = pipeline.ensure_table(api, AIRTABLE_BASE_ID, RAW_TABLE)
    field = name_map.get("ingested_at")
    if not field:
        print(f"  '{RAW_TABLE}' has no ingested_at column and one could not be "
              f"created — skipping.")
        return 0

    records = table.all()
    updates, no_source = [], 0
    for rec in records:
        if (rec["fields"].get(field) or "").strip():
            continue
        stamp = rec.get("createdTime") or rec["fields"].get("date") or ""
        if not stamp:
            no_source += 1
            continue
        updates.append({"id": rec["id"], "fields": {field: stamp}})

    print(f"  {len(records)} rows in '{RAW_TABLE}', {len(updates)} need ingested_at")
    if no_source:
        print(f"  {no_source} row(s) had neither createdTime nor date — left blank "
              f"(dedupe falls back to `date`, so they behave as they did before)")
    batch_update(table, updates, dry_run)
    return len(updates)


def backfill_event_ids(api, dry_run):
    table, name_map = ensure_table(api, AIRTABLE_BASE_ID, dedupe.CLEAN_TABLE,
                                   dedupe.CLEAN_FIELDS)
    id_f = name_map.get("event_id", "event_id")
    url_f = name_map.get("source_urls", "source_urls")

    records = table.all()
    updates, no_urls, already = [], 0, 0
    for rec in records:
        f = rec["fields"]
        current = (f.get(id_f) or "").strip()
        # NEVER recompute an id that is already minted. Under first-writer-wins
        # the id comes from the sources an event was FIRST seen with, and the
        # set grows as more outlets cover the action — so event_id_for(current
        # urls) legitimately diverges from it. Recomputing would change the id
        # of a live event and split it from its own history. Only a legacy
        # uuid4 (or a blank) is eligible.
        if MINTED_ID.match(current):
            already += 1
            continue
        urls = [u.strip() for u in (f.get(url_f) or "").splitlines() if u.strip()]
        if not urls:
            no_urls += 1
            continue
        updates.append({"id": rec["id"], "fields": {id_f: dedupe.event_id_for(urls)}})

    print(f"  {len(records)} rows in '{dedupe.CLEAN_TABLE}', "
          f"{len(updates)} need a minted event_id"
          + (f" ({already} already minted, left alone)" if already else ""))
    if no_urls:
        print(f"  {no_urls} row(s) have no source_urls, so no id can be derived — "
              f"the first run will supersede them if it owns their inputs")

    # Two clean rows sharing a URL set collapse to one id. That's a genuine
    # duplicate the old delete-and-rewrite path could leave behind; report it
    # rather than silently letting the upsert pick a winner.
    seen = {}
    for u in updates:
        seen.setdefault(u["fields"][id_f], []).append(u["id"])
    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    if dupes:
        print(f"  NOTE {len(dupes)} id(s) map to more than one existing row "
              f"({sum(len(v) for v in dupes.values())} rows). These are duplicates "
              f"of the same event; the next dedupe run keeps one.")

    batch_update(table, updates, dry_run)
    return len(updates)


def collapse_duplicates(api, dry_run):
    """Delete all but one of any rows sharing an event_id.

    Keeps a row carrying a human verdict over one that doesn't, then the most
    recently created — it reflects the newest synthesis of the same sources.
    """
    table, name_map = ensure_table(api, AIRTABLE_BASE_ID, dedupe.CLEAN_TABLE,
                                   dedupe.CLEAN_FIELDS)
    id_f = name_map.get("event_id", "event_id")
    review_f = [name_map.get(f, f) for f in dedupe.REVIEW_FIELDS]

    groups = {}
    for rec in table.all():
        eid = (rec["fields"].get(id_f) or "").strip()
        if eid:
            groups.setdefault(eid, []).append(rec)
    dupes = {k: v for k, v in groups.items() if len(v) > 1}

    def rank(rec):
        f = rec["fields"]
        reviewed = any((f.get(rf) or "") not in ("", "unreviewed") for rf in review_f)
        return (reviewed, rec.get("createdTime") or "")

    doomed = []
    for eid, recs in sorted(dupes.items()):
        keep = max(recs, key=rank)
        losers = [r for r in recs if r["id"] != keep["id"]]
        doomed.extend(r["id"] for r in losers)
        print(f"  {eid}: {len(recs)} rows -> keeping {keep['id']} "
              f"(created {(keep.get('createdTime') or '?')[:10]}, "
              f"date {keep['fields'].get('date','??')})")
        for r in losers:
            print(f"      dropping {r['id']} (created "
                  f"{(r.get('createdTime') or '?')[:10]}, "
                  f"date {r['fields'].get('date','??')})")

    if not dupes:
        print(f"  no duplicate event_ids in '{dedupe.CLEAN_TABLE}'")
        return 0

    if not dry_run:
        for i in range(0, len(doomed), 10):
            table.batch_delete(doomed[i:i + 10])
            time.sleep(0.2)
    return len(doomed)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change, write no RECORDS. Missing "
                         "columns are still created — the check needs to know "
                         "they exist, and adding them is additive either way.")
    args = ap.parse_args()

    api = Api(AIRTABLE_TOKEN)

    print(f"1/3  {RAW_TABLE}.ingested_at")
    n_raw = backfill_ingested_at(api, args.dry_run)
    print(f"\n2/3  {dedupe.CLEAN_TABLE}.event_id")
    n_clean = backfill_event_ids(api, args.dry_run)
    # Must run after step 2: the duplicates are only detectable once both rows
    # carry the hash of their (identical) source URLs.
    print(f"\n3/3  {dedupe.CLEAN_TABLE} duplicates")
    n_dropped = collapse_duplicates(api, args.dry_run)

    verb = "would update" if args.dry_run else "updated"
    verb2 = "would delete" if args.dry_run else "deleted"
    print(f"\n{verb} {n_raw} raw row(s) and {n_clean} clean row(s); "
          f"{verb2} {n_dropped} duplicate clean row(s)."
          + ("\n(dry run — nothing written)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
