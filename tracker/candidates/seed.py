#!/usr/bin/env python3
"""Gov Candidates roster — seed/upsert script.

Reads data/candidates_seed.json (the researched 2026 roster) and upserts one row per
candidate into the 'Gov Candidates' Airtable table, matching on (candidate,
state). Fields absent from the JSON (platform_summary, notes, ...) are never
touched on existing rows, so Airtable hand-edits survive re-runs.

Usage:
    python candidates_seed.py                 # upsert from data/candidates_seed.json
    python candidates_seed.py --file f.json   # alternate roster file
    python candidates_seed.py --dry-run       # print what would change
"""

import argparse
import json
import sys
from datetime import datetime, timezone

import os
from dotenv import load_dotenv
from pyairtable import Api

from tracker.paths import DATA

load_dotenv()

AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")
if not (AIRTABLE_TOKEN and AIRTABLE_BASE_ID):
    sys.exit("Missing AIRTABLE_TOKEN / AIRTABLE_BASE_ID. See .env_example.")

CANDIDATES_TABLE = "Gov Candidates"

PARTY_CHOICES = ["R", "D", "I", "L"]
STATUS_CHOICES = [
    "incumbent", "primary-winner", "runoff-pending", "presumptive-nominee",
    "major-contender", "withdrawn", "elected", "defeated",
]
RACE_TYPE_CHOICES = ["open", "incumbent-running"]
RACE_RATING_CHOICES = [
    "Safe R", "Likely R", "Lean R", "Toss-up", "Lean D", "Likely D", "Safe D",
]
COMPETENCY_CHOICES = ["civil-service", "procedure", "digital", "incentives"]

REQUIRED_FIELDS = [
    {"name": "Name", "type": "singleLineText"},
    {"name": "candidate", "type": "singleLineText"},
    {"name": "state", "type": "singleLineText"},
    {"name": "party", "type": "singleSelect",
     "options": {"choices": [{"name": p} for p in PARTY_CHOICES]}},
    {"name": "status", "type": "singleSelect",
     "options": {"choices": [{"name": s} for s in STATUS_CHOICES]}},
    {"name": "current_role", "type": "singleLineText"},
    {"name": "race_type", "type": "singleSelect",
     "options": {"choices": [{"name": r} for r in RACE_TYPE_CHOICES]}},
    {"name": "race_rating", "type": "singleSelect",
     "options": {"choices": [{"name": r} for r in RACE_RATING_CHOICES]}},
    {"name": "primary_date", "type": "date",
     "options": {"dateFormat": {"name": "iso"}}},
    {"name": "primary_held", "type": "checkbox",
     "options": {"icon": "check", "color": "greenBright"}},
    {"name": "website", "type": "url"},
    {"name": "press_url", "type": "url"},
    {"name": "news_query", "type": "singleLineText"},
    {"name": "platform_summary", "type": "multilineText"},
    {"name": "competency_signals", "type": "multipleSelects",
     "options": {"choices": [{"name": c} for c in COMPETENCY_CHOICES]}},
    {"name": "platform_sources", "type": "multilineText"},
    {"name": "platform_asof", "type": "date",
     "options": {"dateFormat": {"name": "iso"}}},
    {"name": "notes", "type": "multilineText"},
    {"name": "seeded_at", "type": "dateTime",
     "options": {"dateFormat": {"name": "iso"},
                 "timeFormat": {"name": "24hour"},
                 "timeZone": "utc"}},
]

# Fields the seed JSON owns; anything else on an existing row is left alone.
SEED_OWNED = [
    "Name", "candidate", "state", "party", "status", "current_role",
    "race_type", "race_rating", "primary_date", "primary_held",
    "website", "press_url", "notes", "seeded_at",
]


def ensure_table(api, base_id, table_name):
    """Same contract as ecosystem_pipeline.ensure_table: returns (table, name_map)."""
    base = api.base(base_id)
    schema = base.schema()
    existing = next((t for t in schema.tables if t.name == table_name), None)
    name_map = {}

    if existing is None:
        created = base.create_table(table_name, fields=REQUIRED_FIELDS)
        print(f"Created Airtable table '{table_name}'")
        for f in REQUIRED_FIELDS:
            name_map[f["name"]] = f["name"]
        table_id = getattr(created, "id", None)
        return (base.table(table_id) if table_id else base.table(table_name)), name_map

    table = base.table(existing.id)
    existing_by_lower = {f.name.lower(): f.name for f in existing.fields}
    for f in REQUIRED_FIELDS:
        canonical = f["name"]
        match = existing_by_lower.get(canonical.lower())
        if match is not None:
            name_map[canonical] = match
            continue
        opts = f.get("options")
        if opts:
            table.create_field(canonical, f["type"], options=opts)
        else:
            table.create_field(canonical, f["type"])
        name_map[canonical] = canonical
        print(f"Added missing field '{canonical}'")
    return table, name_map


def row_from_candidate(state_obj, cand, seeded_at):
    state = state_obj["state"].upper()
    name = cand["name"].strip()
    party = cand.get("party") or ""
    row = {
        "Name": f"{state} — {name}" + (f" ({party})" if party else ""),
        "candidate": name,
        "state": state,
        "seeded_at": seeded_at,
    }
    if party in PARTY_CHOICES:
        row["party"] = party
    status = (cand.get("status") or "").strip()
    if status in STATUS_CHOICES:
        row["status"] = status
    if cand.get("role"):
        row["current_role"] = cand["role"]
    if state_obj.get("race_type") in RACE_TYPE_CHOICES:
        row["race_type"] = state_obj["race_type"]
    rating = (state_obj.get("race_rating") or "").strip()
    if rating in RACE_RATING_CHOICES:
        row["race_rating"] = rating
    if state_obj.get("primary_date"):
        row["primary_date"] = state_obj["primary_date"]
    row["primary_held"] = bool(state_obj.get("primary_held"))
    if cand.get("website"):
        row["website"] = cand["website"]
    if cand.get("press_url"):
        row["press_url"] = cand["press_url"]
    if cand.get("notes"):
        row["notes"] = cand["notes"]
    # The per-candidate Google News override. The field has existed in the
    # schema since the table was created but was never populated here, so it
    # was unreachable: a candidate the press calls by a nickname ("Dan McKee"
    # for Daniel J. McKee) had no way to be searched under it.
    if cand.get("news_query"):
        row["news_query"] = cand["news_query"]
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file",
                    default=os.path.join(DATA, "candidates_seed.json"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(args.file) as fh:
        states = json.load(fh)

    seeded_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for st in states:
        for cand in st.get("candidates", []):
            rows.append(row_from_candidate(st, cand, seeded_at))
    print(f"{args.file}: {len(states)} states, {len(rows)} candidates")

    if args.dry_run:
        for r in rows:
            print(f"  {r['Name']:<40} {r.get('status', '?'):<20} {r.get('race_rating', '')}")
        return

    api = Api(AIRTABLE_TOKEN)
    table, name_map = ensure_table(api, AIRTABLE_BASE_ID, CANDIDATES_TABLE)

    cand_f = name_map.get("candidate", "candidate")
    state_f = name_map.get("state", "state")
    existing = {}
    for rec in table.all(fields=[cand_f, state_f]):
        key = (rec["fields"].get(cand_f, "").strip().lower(),
               rec["fields"].get(state_f, "").strip().upper())
        existing[key] = rec["id"]

    created = updated = 0
    for row in rows:
        mapped = {name_map[k]: v for k, v in row.items() if k in name_map}
        key = (row["candidate"].strip().lower(), row["state"])
        rec_id = existing.get(key)
        if rec_id:
            table.update(rec_id, mapped, typecast=True)
            updated += 1
        else:
            table.create(mapped, typecast=True)
            created += 1
    print(f"Created {created}, updated {updated} rows in '{CANDIDATES_TABLE}'")


if __name__ == "__main__":
    main()
