#!/usr/bin/env python3
"""One-time cleanup for federal rows whose title still carries the Federal
Register search phrase that found them. Idempotent — re-running it is a no-op.

The bug, now fixed at source in federal/sources.py: a Federal Register term
sweep is not agency-scoped, so `pipeline.build_row` fell through to labelling
the raw row with the spec's whole NAME —

    FR term — improper payments — Privacy Act matching program notice…

— and `dedupe.single_row_event` strips only the FIRST " — " segment off that
Name, which peeled off "FR term" and left the search phrase sitting in front of
the event title on the Rulemaking & notices lane. Only the 18 term queries were
affected: the FR agency and FR type specs carry a real `agency`, so their label
holds no em dash and the strip lands where it should.

Two jobs, neither of which costs an LLM call:

1. 'Federal Raw'.Name — rewritten to "Federal Register — <title>", which is
   what the fixed spec produces now. This is the job that MATTERS: the dedupe
   re-reads raw rows by `ingested_at` window and upserts the clean table on
   event_id, so a clean row fixed on its own would have the phrase written back
   over it on the next run that covers the same window.

2. 'Federal Events'.short_title and .Name — the phrase segment removed. Nothing
   re-derives these from a source we can re-run, so they need editing in place.

Both steps are narrow on purpose. A row is only touched when the prefix matches
one of `sources.FEDREG_TERMS` exactly, AND the row's own provenance names that
same term query (`source` on a raw row, `source_outlets` on a clean one). A
title that happens to open with "civil service — " on its own merits is left
alone, because no term sweep will be listed behind it.

Usage:
    python -m tools.strip_fr_term_prefixes --dry-run
    python -m tools.strip_fr_term_prefixes
"""

import argparse
import os
import sys
import time

from dotenv import load_dotenv
from pyairtable import Api

from tracker.federal import schema as fs
from tracker.federal import sources as fsrc
from tracker.shared.airtable import ensure_table

load_dotenv()

AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")

RAW_PREFIX = "FR term — "
# What the fixed spec now puts in the label slot for a term sweep.
OUTLET = "Federal Register"
SEP = " — "

# Bare phrases, in the same form the spec name and the leaked prefix carry.
TERMS = [t.strip('"') for t in fsrc.FEDREG_TERMS]


def leaked_term(title, provenance):
    """The FEDREG_TERM `title` opens with, if the row's provenance names that
    same term query. None when the prefix is the title's own words."""
    for term in TERMS:
        if not title.lower().startswith(term.lower() + SEP):
            continue
        if any(line.strip() == RAW_PREFIX + term for line in provenance):
            return term
    return None


def fix_raw(table, name_map, dry_run):
    """'Federal Raw'.Name -> "Federal Register — <title>"."""
    name_f = name_map.get("Name", "Name")
    source_f = name_map.get("source", "source")

    fixed = 0
    for rec in table.all(fields=[name_f, source_f]):
        f = rec["fields"]
        name = (f.get(name_f) or "").strip()
        source = (f.get(source_f) or "").strip()
        if not name.startswith(RAW_PREFIX) or not source.startswith(RAW_PREFIX):
            continue
        # Name is "FR term — <phrase> — <title>"; the phrase is the source's.
        phrase = source[len(RAW_PREFIX):]
        if phrase not in TERMS or not name.startswith(RAW_PREFIX + phrase + SEP):
            print(f"  SKIP unrecognised term {source!r}: {name[:70]}")
            continue
        title = name[len(RAW_PREFIX + phrase + SEP):]
        new = f"{OUTLET}{SEP}{title}"[:250]
        print(f"  {name[:88]}\n    -> {new[:88]}")
        if not dry_run:
            table.update(rec["id"], {name_f: new})
            time.sleep(0.2)
        fixed += 1
    return fixed


def fix_clean(table, name_map, dry_run):
    """'Federal Events'.short_title and .Name — drop the phrase segment."""
    name_f = name_map.get("Name", "Name")
    title_f = name_map.get("short_title", "short_title")
    outlets_f = name_map.get("source_outlets", "source_outlets")

    fixed = 0
    for rec in table.all(fields=[name_f, title_f, outlets_f]):
        f = rec["fields"]
        title = (f.get(title_f) or "").strip()
        outlets = (f.get(outlets_f) or "").splitlines()
        term = leaked_term(title, outlets)
        if not term:
            continue
        new_title = title[len(term + SEP):]
        patch = {title_f: new_title[:120]}
        # Name is "<agency> — <short_title>"; keep the label, swap the title.
        name = (f.get(name_f) or "").strip()
        if title in name:
            patch[name_f] = name.replace(title, new_title, 1)[:250]
        else:
            print(f"  (Name left alone, does not carry the title: {name[:60]})")
        print(f"  {title[:88]}\n    -> {new_title[:88]}")
        if not dry_run:
            table.update(rec["id"], patch)
            time.sleep(0.2)
        fixed += 1
    return fixed


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    missing = [k for k, v in {"AIRTABLE_TOKEN": AIRTABLE_TOKEN,
                              "AIRTABLE_BASE_ID": AIRTABLE_BASE_ID}.items() if not v]
    if missing:
        sys.exit(f"Missing env vars: {', '.join(missing)}")

    api = Api(AIRTABLE_TOKEN)
    raw, raw_map = ensure_table(api, AIRTABLE_BASE_ID, fs.RAW_TABLE, fs.RAW_FIELDS)
    clean, clean_map = ensure_table(api, AIRTABLE_BASE_ID, fs.EVENTS_TABLE, fs.EVENT_FIELDS)

    print(f"{fs.RAW_TABLE}:")
    n_raw = fix_raw(raw, raw_map, args.dry_run)
    print(f"\n{fs.EVENTS_TABLE}:")
    n_clean = fix_clean(clean, clean_map, args.dry_run)

    verb = "would fix" if args.dry_run else "fixed"
    print(f"\n{verb} {n_raw} raw row(s), {n_clean} event row(s)")
    if args.dry_run:
        print("(dry run — nothing written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
