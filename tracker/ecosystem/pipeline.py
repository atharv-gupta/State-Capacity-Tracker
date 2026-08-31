#!/usr/bin/env python3
"""Ecosystem Writing Tracker — ingest pipeline.

A standalone sibling to the State Capacity Tracker pipeline. Pulls every feed in
ecosystem_sources.all_feeds() (curated Recoding America think-tank / nonprofit partners),
keeps items from the last N days, dedups by URL against the table, then runs a
single content-gate + enrich LLM call per surviving entry and writes one row per
kept piece to the 'Ecosystem Writing' Airtable table.

No keyword pre-screen (every source is trusted skim) and no dedupe.py step (an
essay appears once on its own feed; URL-dedup is the whole dedup story).

Usage:
    python ecosystem_pipeline.py            # daily, last 7 days
    python ecosystem_pipeline.py --days 30  # the seed backfill
    python ecosystem_pipeline.py --dry-run  # enrich but don't write
    python ecosystem_pipeline.py --limit N  # cap items sent to the LLM
"""

import argparse
import concurrent.futures
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

import feedparser
from anthropic import Anthropic
from dotenv import load_dotenv
from pyairtable import Api

from tracker.ecosystem import sources as ecosystem_sources

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
    sys.exit(f"Missing env vars: {', '.join(_missing)}. See .env_example.")

ECOSYSTEM_TABLE = "Ecosystem Writing"
MODEL = "claude-haiku-4-5"
CLASSIFY_WORKERS = 8

# Shallow cap — only so the 30-day backfill reaches a full month on the busier
# feeds (FedScoop, the larger think tanks). Daily 7-day runs won't trigger it.
MAX_FEED_PAGES = 5

PIECE_TYPE_CHOICES = ["essay", "report", "blog-post", "news-analysis", "other"]
TOPIC_CHOICES = [
    "procedure", "digital", "civil-service",
    "state-capacity", "govtech", "public-admin",
]

REQUIRED_FIELDS = [
    {"name": "Name", "type": "singleLineText"},
    {"name": "title", "type": "multilineText"},
    {"name": "org", "type": "singleLineText"},
    {"name": "author", "type": "singleLineText"},
    {"name": "url", "type": "singleLineText"},
    {"name": "published", "type": "date", "options": {"dateFormat": {"name": "iso"}}},
    {"name": "piece_type", "type": "singleSelect",
     "options": {"choices": [{"name": p} for p in PIECE_TYPE_CHOICES]}},
    {"name": "topics", "type": "multipleSelects",
     "options": {"choices": [{"name": t} for t in TOPIC_CHOICES]}},
    {"name": "summary", "type": "multilineText"},
    {"name": "source_domain", "type": "singleLineText"},
    {"name": "ingested_at", "type": "dateTime",
     "options": {"dateFormat": {"name": "iso"},
                 "timeFormat": {"name": "24hour"},
                 "timeZone": "utc"}},
]

SYSTEM_PROMPT = """You enrich one piece of writing from a curated Recoding America partner
outlet for the Ecosystem Writing tracker. The outlets are pre-trusted, so there
is NO relevance gate.

Apply ONE gate, and it is purely about FORMAT, not subject matter. There are
EXACTLY FIVE valid reasons to fail a piece — keep=false ONLY if one of these
precisely describes the item:
  1. audio/video-only — a podcast or webinar episode with no article text;
  2. an event listing or event announcement with no substantive written body;
  3. a job posting or hiring announcement;
  4. a donation, membership, or subscription/marketing page;
  5. a pure link roundup or open discussion/thread prompt with no original
     writing of its own (e.g. a "Tuesday discussion post" that only invites
     comments).
An audio/video item WITH a real written companion article PASSES — treat the
article as the piece. If NONE of those five precisely fits, you MUST output
keep=true. When in doubt, keep.

A truncated body is NOT a failure. Many feeds publish only the opening
paragraphs of an article followed by "Read more" / "Continue reading" — that
excerpt is still a real written piece, so KEEP it. Treat reason 5 as applying
ONLY to posts that are nothing but links or a bare discussion prompt, never to a
genuine article that happens to be truncated in the feed.

CRITICAL: relevance is NOT one of the five and is NEVER a reason to fail. Do NOT
fail a piece because its topic seems off-mission, off-topic, niche, academic, or
outside government/policy. A guest essay, an op-ed, a personal reflection, or a
piece on a social, cultural, or political subject is substantive written prose —
KEEP it, even if it has nothing to do with government, administration, or any of
the six topic tags below. The
topic tags below are for labeling, never for rejecting — if none of the six
topics fit, return an empty topics list and still keep the piece.

If it passes, output ONLY this JSON object:
{
  "keep": true,
  "title": "clean title",
  "author": "author name(s), or \\"\\" if absent",
  "piece_type": "one of: essay | report | blog-post | news-analysis | other",
  "topics": ["one or more of: procedure | digital | civil-service | state-capacity | govtech | public-admin"],
  "summary": "one plain sentence, your own words, what the piece argues or reports"
}

Topic guidance:
- "procedure"      — deproceduralization, regulatory simplification, permitting, licensing, red tape.
- "digital"        — digital & tech transformation, digital services, modernization, AI in government.
- "civil-service"  — civil service & workforce reform, hiring, personnel, public-sector talent.
- "state-capacity" — the broader capacity of government to deliver; institutional effectiveness.
- "govtech"        — government technology vendors, procurement of tech, govtech ecosystem.
- "public-admin"   — public administration scholarship, management, organizational practice.
Pick every topic that genuinely applies; do not force a pillar tag if it does not fit.

If it fails, output ONLY:
{"keep": false, "reason": "one short line"}

Output ONLY the JSON object. No markdown fences, no preamble, no trailing text.
"""


# --- Helpers lifted verbatim from pipeline.py (ecosystem-tracker-spec §3) -----

def parse_feed(url):
    """feedparser catches most errors into .bozo, but raw socket failures
    (e.g. a CDN dropping the connection, common from CI runner IPs) can
    still raise — one flaky outlet must never kill the run."""
    try:
        return feedparser.parse(url).entries
    except Exception as e:
        print(f"  fetch error {url}: {e}")
        return []


def entry_date(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return date(t.tm_year, t.tm_mon, t.tm_mday)
    return None


def strip_html(text):
    return re.sub(r"<[^>]+>", " ", text or "")


def parse_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


def ensure_table(api, base_id, table_name):
    """Returns (table, name_map). name_map maps our canonical field name to
    the actual Airtable field name (case may differ if it pre-existed)."""
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


def existing_source_urls(table, name_map):
    """URLs already in the table, so re-runs skip ingested pieces."""
    field = name_map.get("url", "url")
    urls = set()
    for rec in table.all(fields=[field]):
        val = (rec["fields"].get(field) or "").strip()
        if val:
            urls.add(val)
    return urls


# --- Ecosystem-specific stages -----------------------------------------------

def fetch_feed(spec, min_date):
    """Fetch a feed, paging backwards through WordPress-style ?paged=N pages
    until entries are older than min_date (shallow cap MAX_FEED_PAGES). Mirrors
    the state pipeline's backward-paging; non-WordPress feeds ignore ?paged=
    and return duplicate entries, which ends the loop."""
    org, url, source_domain = spec
    entries = parse_feed(url)
    if not entries:
        print(f"  FEED EMPTY/FAILED {org}")
        return spec, []
    seen_links = {e.get("link", "") for e in entries}
    batch = entries

    def oldest(b):
        ds = [d for d in (entry_date(e) for e in b) if d]
        return min(ds) if ds else None

    for page in range(2, MAX_FEED_PAGES + 1):
        o = oldest(batch)
        if o is None or o < min_date:
            break
        sep = "&" if "?" in url else "?"
        more = parse_feed(f"{url}{sep}paged={page}")
        fresh = [e for e in more if e.get("link", "") not in seen_links]
        if not fresh:
            break
        seen_links.update(e.get("link", "") for e in fresh)
        entries.extend(fresh)
        batch = fresh
    return spec, entries


def extract_piece(spec, entry):
    org, url, source_domain = spec
    pub = entry_date(entry)
    # Prefer full content body when present (Substack/WordPress put the article
    # in content[]); fall back to summary. The content gate needs real text.
    body = ""
    if entry.get("content"):
        body = entry["content"][0].get("value", "")
    body = body or entry.get("summary", "")
    return {
        "org": org,
        "source_domain": source_domain,
        "title": entry.get("title", ""),
        "author": entry.get("author", ""),
        "published": pub.isoformat() if pub else "",
        "pub_date": pub,
        "url": entry.get("link", ""),
        "summary": strip_html(body)[:2000].strip(),
    }


def enrich(client, piece):
    user_msg = json.dumps({
        "org": piece["org"],
        "title": piece["title"],
        "feed_author": piece["author"],
        "published": piece["published"],
        "url": piece["url"],
        "body": piece["summary"],
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


def valid_topics(verdict):
    topics = verdict.get("topics") or []
    if isinstance(topics, str):
        topics = [topics]
    return [t for t in topics if t in TOPIC_CHOICES]


def build_row(piece, verdict, topics, ingested_at):
    title = (verdict.get("title") or piece["title"]).strip()
    piece_type = verdict.get("piece_type") or ""
    row = {
        "Name": f"{piece['org']} — {title}"[:255],
        "title": title,
        "org": piece["org"],
        "author": (verdict.get("author") or piece["author"] or "").strip(),
        "url": piece["url"],
        "summary": (verdict.get("summary") or "").strip(),
        "source_domain": piece["source_domain"],
        "ingested_at": ingested_at,
    }
    if piece["published"]:
        row["published"] = piece["published"]
    row["piece_type"] = piece_type if piece_type in PIECE_TYPE_CHOICES else "other"
    if topics:
        row["topics"] = topics
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=7, help="lookback window in days (default 7)")
    ap.add_argument("--dry-run", action="store_true", help="enrich but don't write to Airtable")
    ap.add_argument("--limit", type=int, default=0, help="cap items sent to the LLM")
    args = ap.parse_args()

    min_date = date.today() - timedelta(days=args.days)
    ingested_at = datetime.now(timezone.utc).isoformat()

    feed_specs = list(ecosystem_sources.all_feeds())

    print(f"Fetching {len(feed_specs)} feeds (window: since {min_date})...")
    pieces = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        for spec, entries in ex.map(lambda s: fetch_feed(s, min_date), feed_specs):
            pieces.extend(extract_piece(spec, e) for e in entries)
    print(f"Got {len(pieces)} entries\n")

    fresh = [p for p in pieces if p["pub_date"] and p["pub_date"] >= min_date]
    print(f"Date gate (>= {min_date}): {len(fresh)} kept, {len(pieces) - len(fresh)} dropped")

    # Drop entries with no URL (can't dedup or link them).
    fresh = [p for p in fresh if p["url"]]

    if args.limit and len(fresh) > args.limit:
        fresh = fresh[:args.limit]
        print(f"--limit:                   capped at {args.limit}")

    if not fresh:
        print("Nothing to enrich.")
        return

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    table, name_map = None, {}
    if not args.dry_run:
        api = Api(AIRTABLE_TOKEN)
        table, name_map = ensure_table(api, AIRTABLE_BASE_ID, ECOSYSTEM_TABLE)
        seen = existing_source_urls(table, name_map)
        before = len(fresh)
        fresh = [p for p in fresh if p["url"] not in seen]
        if before - len(fresh):
            print(f"Already in Airtable:       {before - len(fresh)} skipped")
        if not fresh:
            print("Nothing new to enrich.")
            return

    kept, dropped, errors = [], [], []
    done = 0

    print(f"\nEnriching {len(fresh)} pieces with {MODEL} "
          f"({CLASSIFY_WORKERS} workers)...")

    def work(piece):
        return piece, enrich(client, piece)

    with concurrent.futures.ThreadPoolExecutor(max_workers=CLASSIFY_WORKERS) as ex:
        futures = [ex.submit(work, p) for p in fresh]
        for fut in concurrent.futures.as_completed(futures):
            done += 1
            try:
                p, verdict = fut.result()
            except Exception as e:
                errors.append(("?", f"enrich: {e}"))
                print(f"  [{done}/{len(fresh)}] ERROR — {e}")
                continue

            if not verdict.get("keep"):
                reason = verdict.get("reason") or "content gate failed"
                dropped.append((p, reason))
                print(f"  [{done}/{len(fresh)}] DROP {p['org'][:18]} — {reason[:60]}")
                continue

            topics = valid_topics(verdict)
            kept.append((p, verdict, topics))
            print(f"  [{done}/{len(fresh)}] KEEP {p['org'][:18]} — "
                  f"{(verdict.get('title') or p['title'])[:60]}")

    written = 0
    if not args.dry_run and kept:
        print(f"\nWriting {len(kept)} rows to '{ECOSYSTEM_TABLE}'...")
        for p, verdict, topics in kept:
            row = build_row(p, verdict, topics, ingested_at)
            row = {name_map[k]: v for k, v in row.items() if k in name_map}
            try:
                table.create(row, typecast=True)
                written += 1
            except Exception as e:
                errors.append((p["title"], f"airtable: {e}"))
                print(f"  ERROR — airtable: {e}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Feeds:       {len(feed_specs)}")
    print(f"Entries:     {len(pieces)}")
    print(f"In window:   {len(fresh) if args.dry_run else '(see above)'}")
    print(f"Enriched:    {len(fresh)}")
    print(f"Kept:        {len(kept)}")
    print(f"Dropped:     {len(dropped)}")
    print(f"Errors:      {len(errors)}")
    if not args.dry_run:
        print(f"Written:     {written}")

    if kept:
        print("\n--- KEPT ---")
        for p, v, topics in sorted(kept, key=lambda x: (x[0]["org"], x[0]["published"])):
            print(f"  {p['published']} [{','.join(topics) or '-'}] "
                  f"{v.get('piece_type', '?')} — {p['org']}: "
                  f"{(v.get('title') or p['title'])[:60]}")
            if v.get("summary"):
                print(f"     {v['summary'][:100]}")

    if dropped:
        print("\n--- DROPPED (content gate) ---")
        for p, reason in dropped:
            print(f"  {p['org']}: {p['title'][:60]}")
            print(f"     {reason}")

    if errors:
        print("\n--- ERRORS ---")
        for title, err in errors:
            print(f"  {str(title)[:60]}: {err}")


if __name__ == "__main__":
    main()
