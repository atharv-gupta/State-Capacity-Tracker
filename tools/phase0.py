#!/usr/bin/env python3
"""Phase 0 — State Capacity Tracker single-feed pipeline.

Fetches one Google News query feed, decodes redirect URLs, applies the
provenance + pillar gates from docs/SPEC.md §3 via the Anthropic API, and writes
survivors to Airtable.
"""

import json
import os
import sys
import time
import urllib.parse
import uuid

import feedparser
from anthropic import Anthropic
from dotenv import load_dotenv
from googlenewsdecoder import gnewsdecoder
from pyairtable import Api

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")

_missing = [
    k for k, v in {
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "AIRTABLE_TOKEN": AIRTABLE_TOKEN,
        "AIRTABLE_BASE_ID": AIRTABLE_BASE_ID,
    }.items() if not v
]
if _missing:
    sys.exit(f"Missing env vars: {', '.join(_missing)}. See .env.example.")

TABLE_NAME = "Events"
MODEL = "claude-haiku-4-5"
QUERY = '"Colorado" "Office of Information Technology"'
FEED_URL = (
    "https://news.google.com/rss/search"
    f"?q={urllib.parse.quote(QUERY)}&hl=en-US&gl=US&ceid=US:en"
)

PILLAR_CHOICES = ["deproc", "digital", "civil-service"]
ACTIVITY_TYPE_CHOICES = [
    "bill-introduced", "bill-passed", "EO", "rulemaking", "appointment",
    "reorg", "RFP/procurement", "budget", "program-launch", "audit/report",
]

REQUIRED_FIELDS = [
    {"name": "event_id", "type": "singleLineText"},
    {"name": "date", "type": "date", "options": {"dateFormat": {"name": "iso"}}},
    {"name": "state", "type": "singleLineText"},
    {"name": "pillars", "type": "multipleSelects",
     "options": {"choices": [{"name": p} for p in PILLAR_CHOICES]}},
    {"name": "activity_type", "type": "singleSelect",
     "options": {"choices": [{"name": a} for a in ACTIVITY_TYPE_CHOICES]}},
    {"name": "gov_actor", "type": "singleLineText"},
    {"name": "headline", "type": "multilineText"},
    {"name": "significance", "type": "number", "options": {"precision": 0}},
    {"name": "why_it_matters", "type": "multilineText"},
    {"name": "source_urls", "type": "multilineText"},
    {"name": "source_outlets", "type": "singleLineText"},
    {"name": "status", "type": "singleLineText"},
]

SYSTEM_PROMPT = """You classify news articles for the Recoding America State Capacity Tracker.

For each article, apply two gates:

GATE 1 — PROVENANCE: Is the underlying activity an action by a government actor
in their official capacity?
  PASS examples: bill (introduced or passed), executive order, rulemaking,
  appointment, agency reorg, RFP/procurement, budget move, program launch,
  official audit/report. A vendor press release announcing a state contract
  award PASSES because the award itself is a government action.
  FAIL examples: think-tank reports, advocacy, campaign promises, punditry,
  general industry news, opinion pieces.

GATE 2 — PILLAR: Does it touch at least one of:
  - "deproc"        — Deproceduralization / Regulatory simplification
  - "digital"       — Digital & tech transformation
  - "civil-service" — Civil service & workforce reform

If BOTH gates pass, output ONLY this JSON object:
{
  "pass": true,
  "date": "YYYY-MM-DD",
  "state": "CO",
  "pillars": ["digital"],
  "activity_type": "one of: bill-introduced | bill-passed | EO | rulemaking | appointment | reorg | RFP/procurement | budget | program-launch | audit/report",
  "gov_actor": "e.g., CO Office of Information Technology",
  "headline": "one-line what happened, in your own words",
  "significance": 3,
  "why_it_matters": "optional one line for the digest, empty string if none",
  "status": "optional: introduced | enacted | etc., empty string if N/A"
}

If EITHER gate fails, output ONLY:
{"pass": false, "reason": "which gate failed and why, one short line"}

Output ONLY the JSON object. No markdown fences, no preamble, no trailing text.
"""


def fetch_feed(url):
    print(f"Fetching: {url}")
    parsed = feedparser.parse(url)
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(f"Feed parse failed: {parsed.bozo_exception}")
    return parsed.entries


def extract_article(entry):
    source = entry.get("source") if hasattr(entry, "get") else None
    if source is None:
        source = getattr(entry, "source", None)
    publisher = ""
    if source is not None:
        publisher = (
            source.get("title", "") if hasattr(source, "get")
            else getattr(source, "title", "")
        )
    return {
        "title": entry.get("title", ""),
        "publisher": publisher,
        "published": entry.get("published", ""),
        "google_url": entry.get("link", ""),
        "summary": entry.get("summary", ""),
    }


def decode_url(google_url):
    try:
        result = gnewsdecoder(google_url, interval=1)
        if result.get("status") and result.get("decoded_url"):
            return result["decoded_url"]
        print(f"  decode failed: {result.get('message', 'unknown')}")
    except Exception as e:
        print(f"  decode error: {e}")
    return google_url


def parse_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


def classify(client, article):
    user_msg = json.dumps({
        "title": article["title"],
        "publisher": article["publisher"],
        "published": article["published"],
        "url": article["url"],
        "summary": article.get("summary", ""),
    })
    resp = client.messages.create(
        model=MODEL,
        max_tokens=600,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_msg}],
    )
    return parse_json_response(resp.content[0].text)


def ensure_table(api, base_id, table_name):
    """Returns (table, name_map). name_map maps our canonical field name
    (lowercase, matching docs/SPEC.md §6) to the actual Airtable field name on
    the table — which may differ in case if the field pre-existed."""
    base = api.base(base_id)
    schema = base.schema()
    existing = next((t for t in schema.tables if t.name == table_name), None)
    name_map = {}

    if existing is None:
        created = base.create_table(table_name, fields=REQUIRED_FIELDS)
        print(f"Created Airtable table '{table_name}' with {len(REQUIRED_FIELDS)} fields")
        for f in REQUIRED_FIELDS:
            name_map[f["name"]] = f["name"]
        table_id = getattr(created, "id", None)
        table = base.table(table_id) if table_id else base.table(table_name)
        return table, name_map

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


def existing_source_urls(table, name_map):
    """URLs already written to the table, so re-runs skip seen articles."""
    field = name_map.get("source_urls", "source_urls")
    urls = set()
    for rec in table.all(fields=[field]):
        for line in (rec["fields"].get(field) or "").splitlines():
            line = line.strip()
            if line:
                urls.add(line)
    return urls


def build_row(article, verdict):
    row = {
        "event_id": str(uuid.uuid4()),
        "state": (verdict.get("state") or "").upper()[:2],
        "gov_actor": verdict.get("gov_actor") or "",
        "headline": verdict.get("headline") or article["title"],
        "why_it_matters": verdict.get("why_it_matters") or "",
        "source_urls": article["url"],
        "source_outlets": article["publisher"] or "",
        "status": verdict.get("status") or "",
    }

    date_val = verdict.get("date") or ""
    if date_val and len(date_val) == 10 and date_val[4] == "-" and date_val[7] == "-":
        row["date"] = date_val

    pillars = verdict.get("pillars") or []
    if isinstance(pillars, str):
        pillars = [pillars]
    pillars = [p for p in pillars if p in PILLAR_CHOICES]
    if pillars:
        row["pillars"] = pillars

    activity = verdict.get("activity_type") or ""
    if activity in ACTIVITY_TYPE_CHOICES:
        row["activity_type"] = activity

    try:
        sig = int(verdict.get("significance") or 0)
        if 1 <= sig <= 5:
            row["significance"] = sig
    except (TypeError, ValueError):
        pass

    return row


def main():
    entries = fetch_feed(FEED_URL)
    print(f"Got {len(entries)} entries from Google News\n")
    if not entries:
        print("No entries to process.")
        return

    articles = [extract_article(e) for e in entries]

    print("Decoding Google News redirect URLs...")
    for i, a in enumerate(articles, 1):
        a["url"] = decode_url(a["google_url"])
        if i % 10 == 0:
            print(f"  decoded {i}/{len(articles)}")
    print(f"  done ({len(articles)})\n")

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    api = Api(AIRTABLE_TOKEN)
    table, name_map = ensure_table(api, AIRTABLE_BASE_ID, TABLE_NAME)

    seen = existing_source_urls(table, name_map)
    before = len(articles)
    articles = [a for a in articles if a["url"] not in seen]
    skipped = before - len(articles)
    if skipped:
        print(f"Skipping {skipped} articles already in Airtable")
    if not articles:
        print("No new articles to classify.")
        return

    passed, dropped, errors = [], [], []

    print(f"\nClassifying {len(articles)} articles with {MODEL}...")
    for i, a in enumerate(articles, 1):
        try:
            verdict = classify(client, a)
        except Exception as e:
            errors.append((a["title"], f"classify: {e}"))
            print(f"  [{i}/{len(articles)}] ERROR — {e}")
            continue

        if not verdict.get("pass"):
            dropped.append((a["title"], verdict.get("reason", "no reason")))
            print(f"  [{i}/{len(articles)}] DROP — {verdict.get('reason', '')[:80]}")
            continue

        row = build_row(a, verdict)
        row = {name_map[k]: v for k, v in row.items() if k in name_map}
        try:
            table.create(row, typecast=True)
            passed.append((a, verdict))
            print(f"  [{i}/{len(articles)}] PASS — {verdict.get('headline', '')[:80]}")
        except Exception as e:
            errors.append((a["title"], f"airtable: {e}"))
            print(f"  [{i}/{len(articles)}] ERROR — airtable: {e}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Query:    {QUERY}")
    print(f"Fetched:  {len(articles)}")
    print(f"Passed:   {len(passed)}")
    print(f"Dropped:  {len(dropped)}")
    print(f"Errors:   {len(errors)}")

    if passed:
        print("\n--- PASSED (written to Airtable) ---")
        for a, v in passed:
            pillars = ",".join(v.get("pillars", []))
            print(f"  • [{pillars}] {v.get('activity_type', '?')} — {v.get('headline', '')}")
            print(f"    src: {a['publisher']} — {a['title'][:80]}")

    if dropped:
        print("\n--- DROPPED ---")
        for title, reason in dropped:
            print(f"  • {title[:80]}")
            print(f"    {reason}")

    if errors:
        print("\n--- ERRORS ---")
        for title, err in errors:
            print(f"  • {title[:80]}")
            print(f"    {err}")


if __name__ == "__main__":
    main()
