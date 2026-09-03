#!/usr/bin/env python3
"""Merge groups of 'Events' rows that describe the same government action.

state/dedupe.py reports these rather than merging them: under first-writer-wins
it will not choose whose frozen text survives (see its module docstring). This
script makes that choice explicit and reusable — feed it the event_id groups the
dedupe printed.

**The FIRST iteration wins.** The survivor is the row with the earliest `date`
(ties broken by whichever has more sources), and its text and competency are
kept exactly as they are. The later rows' sources nest under it and the rows
themselves go away.

That is the same rule the daily dedupe follows, and for the same reason: a
later article about an action already recorded is not a new judgment about it.
Keeping the first pass means an event is written once and then stops moving —
it does not resurface week after week as coverage trickles in, and nothing a
reader has seen gets reworded underneath them.

The cost is that the surviving headline describes the stage the action was at
when it was FIRST seen. A budget first recorded as "the Assembly passed X"
keeps that framing after the governor signs it; the signing coverage becomes
more sources on the same event rather than a new headline. That is the intended
trade — resurfacing is worse than a slightly stale verb.

`--resynthesize` opts into rewriting the survivor's text from all the merged
sources instead. It is NOT the default and is rarely what you want: it costs a
synthesis call plus a classify call per group, and it reintroduces exactly the
churn the freeze exists to prevent. It is here for the case where the first
pass is genuinely wrong rather than merely early.

The losers' sources are merged into the survivor before they are deleted. That
matters: an orphaned source URL belongs to no event, so the next dedupe run sees
it as unseen and re-creates the row this script just removed.

Reviewer annotations are never silently dropped — if a loser carries any and the
survivor does not, they are carried across, and the move is printed.

Usage:
    python -m tools.collapse_state_events ID,ID [ID,ID,ID ...] --dry-run
    python -m tools.collapse_state_events ID,ID [ID,ID,ID ...]
"""

import argparse
import os
import sys
import time

from dotenv import load_dotenv
from pyairtable import Api

from anthropic import Anthropic

from tracker.shared.airtable import ensure_table
from tracker.state import dedupe

load_dotenv()

AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")
if not all([AIRTABLE_TOKEN, AIRTABLE_BASE_ID]):
    sys.exit("Missing env vars; see .env_example.")


def merge_list(field_values, sep):
    out = []
    for v in field_values:
        for part in (v or "").split(sep):
            p = part.strip()
            if p and p not in out:
                out.append(p)
    return out


_client = None
_raw_by_url = None


def resynthesized(keep, urls, name_map):
    """Regenerate the survivor's frozen fields from every merged source.

    Reads the ORIGINAL raw articles behind those URLs, not the clean rows, so
    the synthesis sees what the outlets actually reported rather than an
    earlier model's summary of them.
    """
    global _client, _raw_by_url
    F = lambda k: name_map.get(k, k)                      # noqa: E731
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    if _raw_by_url is None:
        api = Api(AIRTABLE_TOKEN)
        base = api.base(AIRTABLE_BASE_ID)
        raw = base.table(next(t.id for t in base.schema().tables
                              if t.name == "Raw Events"))
        _raw_by_url = {}
        for r in raw.all():
            for u in (r["fields"].get("source_urls") or "").splitlines():
                if u.strip():
                    _raw_by_url[u.strip()] = (r["id"], r["fields"])

    members = [_raw_by_url[u] for u in urls if u in _raw_by_url]
    missing = len(urls) - len(members)
    if not members:
        print("    (no raw rows found for these URLs — text left as it is)")
        return {}
    state = keep["fields"].get(F("state"), "??")
    ev = dedupe.synthesize_one(_client, state, members)
    verdict = dedupe.classify_event(_client, ev) or {}
    ev["competencies"] = verdict.get("competencies") or []
    ev["relevance"] = verdict.get("relevance") or 0
    ev["topic_tags"] = verdict.get("topic_tags") or []

    row = dedupe.build_event_row(state, ev, members,
                                 keep["fields"].get(F("event_id"), ""),
                                 (urls, [], []))
    # Provenance is already merged by the caller; take only the frozen half,
    # and never the event_id — identity does not move.
    out = {name_map[k]: row[k] for k in dedupe.FROZEN_FIELDS
           if k in row and k in name_map}

    # Never silently downgrade a classified event to none. The classifier is
    # not deterministic — a competency moved on 1 of 29 events between two
    # identical runs — and the default web view hides competency-empty rows, so
    # an unlucky re-roll would make this event disappear from the dashboard.
    # Re-synthesis is asked for to improve the TEXT; losing the classification
    # is collateral, so keep the stored verdict and say so.
    stored = keep["fields"].get(F("competency")) or []
    if stored and not row.get("competency"):
        for f in ("competency", "relevance", "topic_tags"):
            out.pop(name_map.get(f, f), None)
        print(f"    KEPT stored classification {stored} — the re-classify "
              f"returned none, and that would hide the event")

    print(f"    resynthesized from {len(members)} raw article(s)"
          + (f" ({missing} URL had no raw row)" if missing else ""))
    print(f"      headline: {row.get('headline', '')}")
    print(f"      why:      {row.get('why_it_matters', '')}")
    final_comp = out.get(name_map.get("competency", "competency"), stored)
    print(f"      competency: {final_comp or []}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("groups", nargs="+",
                    help="comma-separated event_ids, one group per argument")
    ap.add_argument("--clean-table", default=dedupe.CLEAN_TABLE)
    ap.add_argument("--resynthesize", action="store_true",
                    help="rewrite the survivor's headline / notes / "
                         "why_it_matters / competency from all the merged "
                         "sources. NOT the default and rarely wanted: it costs "
                         "two model calls per group and reintroduces the churn "
                         "the freeze exists to prevent. Use it only when the "
                         "first pass is wrong, not merely early.")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change, write nothing")
    args = ap.parse_args()

    api = Api(AIRTABLE_TOKEN)
    table, name_map = ensure_table(api, AIRTABLE_BASE_ID, args.clean_table,
                                   dedupe.CLEAN_FIELDS)
    F = lambda k: name_map.get(k, k)          # noqa: E731  canonical -> actual

    by_id = {}
    for rec in table.all():
        eid = (rec["fields"].get(F("event_id")) or "").strip()
        if eid:
            by_id.setdefault(eid, []).append(rec)

    doomed, updates, problems = [], [], []
    for spec in args.groups:
        ids = [i.strip() for i in spec.split(",") if i.strip()]
        recs = []
        for eid in ids:
            hits = by_id.get(eid) or []
            if len(hits) != 1:
                problems.append(f"{eid}: found {len(hits)} rows, expected 1")
            recs.extend(hits)
        if len(recs) < 2 and not args.resynthesize:
            problems.append(f"{spec}: fewer than 2 rows resolved, skipped")
            continue
        if not recs:
            problems.append(f"{spec}: no rows resolved, skipped")
            continue

        # First iteration wins: earliest date, then whichever saw more sources.
        keep = min(recs, key=lambda r: (r["fields"].get(F("date")) or "9999-99-99",
                                        -(r["fields"].get(F("article_count")) or 0)))
        losers = [r for r in recs if r["id"] != keep["id"]]

        urls = merge_list([r["fields"].get(F("source_urls")) for r in recs], "\n")
        outlets = merge_list([r["fields"].get(F("source_outlets")) for r in recs], ",")
        types = merge_list([r["fields"].get(F("source_type")) for r in recs], ",")

        payload = {
            F("source_urls"): "\n".join(urls),
            F("source_outlets"): ", ".join(outlets),
            F("source_type"): ", ".join(types),
            F("article_count"): len(urls),
        }

        # Never lose a human verdict that only the doomed row carries.
        for rf in dedupe.REVIEW_FIELDS:
            if keep["fields"].get(F(rf)):
                continue
            donor = next((r for r in losers if r["fields"].get(F(rf))), None)
            if donor:
                payload[F(rf)] = donor["fields"][F(rf)]
                print(f"  carried {rf} across from {donor['fields'].get(F('event_id'))}")

        kf = keep["fields"]
        print(f"\n{kf.get(F('state'), '??')}  keeping {kf.get(F('event_id'))} "
              f"(date {kf.get(F('date'), '??')}, the first iteration)")
        print(f"    {(kf.get(F('headline')) or '')[:76]}")
        print(f"    sources {kf.get(F('article_count'))} -> {len(urls)}")
        for r in losers:
            lf = r["fields"]
            print(f"  dropping {lf.get(F('event_id'))} (date {lf.get(F('date'), '??')}, "
                  f"n={lf.get(F('article_count'))})")
            print(f"    {(lf.get(F('headline')) or '')[:76]}")

        if args.resynthesize:
            payload.update(resynthesized(keep, urls, name_map))
        updates.append((keep["id"], payload))
        doomed.extend(r["id"] for r in losers)

    if problems:
        print("\n--- PROBLEMS ---")
        for p in problems:
            print(f"  {p}")

    if not args.dry_run:
        for rec_id, payload in updates:
            table.update(rec_id, payload, typecast=True)
            time.sleep(0.2)
        for i in range(0, len(doomed), 10):
            table.batch_delete(doomed[i:i + 10])
            time.sleep(0.2)

    verb = "would merge" if args.dry_run else "merged"
    print(f"\n{verb} {len(updates)} group(s), {verb.split()[0]} "
          f"{'delete' if args.dry_run else 'deleted'} {len(doomed)} row(s)."
          + ("\n(dry run — nothing written)" if args.dry_run else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
