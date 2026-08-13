#!/usr/bin/env python3
"""Shared Airtable helpers.

`ensure_table` exists as a near-identical copy in pipeline.py, phase0.py,
ecosystem_pipeline.py, candidates_pipeline.py and candidates_seed.py, each
closing over that module's own REQUIRED_FIELDS global. This version takes the
field list as an argument so the congress scripts can share one copy. The
older scripts are left alone.
"""

import time


def ensure_table(api, base_id, table_name, fields):
    """Create the table if missing, add any missing fields, and return
    (table, name_map). name_map maps our canonical field name to the actual
    Airtable field name — a pre-existing column with different casing still
    resolves, and a canonical name absent from the map is silently dropped on
    write, so always build rows through it."""
    base = api.base(base_id)
    schema = base.schema()
    existing = next((t for t in schema.tables if t.name == table_name), None)
    name_map = {}

    if existing is None:
        created = base.create_table(table_name, fields=fields)
        print(f"Created Airtable table '{table_name}'")
        for f in fields:
            name_map[f["name"]] = f["name"]
        table_id = getattr(created, "id", None)
        return (base.table(table_id) if table_id else base.table(table_name)), name_map

    table = base.table(existing.id)
    existing_by_lower = {f.name.lower(): f.name for f in existing.fields}
    for f in fields:
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


def remap(row, name_map):
    """Rewrite a canonical-keyed row to Airtable field names, dropping keys
    the table doesn't have."""
    return {name_map[k]: v for k, v in row.items() if k in name_map}


def index_by(table, name_map, key_field):
    """Map {key_field value -> (record_id, fields)} for every row in a table.
    Used by the congress upsert path: unlike the state pipeline's
    delete-then-rewrite, we update in place so human review annotations
    survive a re-run."""
    field = name_map.get(key_field, key_field)
    out = {}
    for rec in table.all():
        k = (rec["fields"].get(field) or "").strip()
        if k:
            out[k] = (rec["id"], rec["fields"])
    return out


def upsert(table, name_map, rows, key_field, preserve=(), dry_run=False):
    """Create or update rows keyed on key_field.

    `preserve` names fields that belong to humans, not the pipeline: if the
    existing record has a value, it wins over whatever we computed. That's what
    keeps review_status/reviewer_notes from being clobbered nightly.

    Returns (created, updated).
    """
    if not rows:
        return 0, 0
    index = index_by(table, name_map, key_field)
    created = updated = 0
    to_create = []

    for row in rows:
        key = (row.get(key_field) or "").strip()
        if not key:
            continue
        hit = index.get(key)
        if hit is None:
            to_create.append(remap(row, name_map))
            created += 1
            continue
        rec_id, existing_fields = hit
        payload = dict(row)
        for f in preserve:
            actual = name_map.get(f, f)
            if existing_fields.get(actual):
                payload.pop(f, None)
        mapped = remap(payload, name_map)
        # Only write when something actually changed — avoids burning Airtable
        # quota re-writing identical rows every night.
        if any(existing_fields.get(k) != v for k, v in mapped.items()):
            if not dry_run:
                table.update(rec_id, mapped, typecast=True)
            updated += 1

    if to_create and not dry_run:
        for i in range(0, len(to_create), 10):
            table.batch_create(to_create[i:i + 10], typecast=True)
            time.sleep(0.2)
    return created, updated
