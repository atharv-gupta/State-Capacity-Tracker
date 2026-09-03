#!/usr/bin/env python3
"""State Capacity Tracker — ingest pipeline (raw layer).

Pulls every feed in sources.py (States Newsroom spine + per-state newspapers
+ national trade press), keeps items from the last N days (default 7),
pre-screens with pillar keywords (cheap, before any LLM call), runs the
provenance + pillar gates from docs/SPEC.md §3 with a fast Claude model, and
writes one row per surviving ARTICLE to the 'Raw Events' Airtable table.

dedupe.py then clusters raw rows into one row per EVENT in 'Events'.

Usage:
    python pipeline.py                 # all feeds, last 7 days
    python pipeline.py CO KS MI        # only these states (+ national feeds)
    python pipeline.py --days 14       # widen the window
    python pipeline.py --dry-run       # classify but don't write
    python pipeline.py --limit 20      # cap articles sent to the classifier
"""

import argparse
import concurrent.futures
import json
import os
import re
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

import feedparser
from anthropic import Anthropic
from dotenv import load_dotenv
from tracker.shared.wim import RULES
from pyairtable import Api

from tracker.state import sources

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

RAW_TABLE = "Raw Events"
MODEL = "claude-haiku-4-5"
CLASSIFY_WORKERS = 8

# ---------------------------------------------------------------------------
# Keyword pre-screen — docs/SPEC.md §4: "the highest-leverage and highest-risk
# component... treat them as a living, reviewed artifact." Misses come from
# words missing here, not from outlets. Review and extend these lists.
# Matched case-insensitively on word boundaries against title + summary.
# ---------------------------------------------------------------------------
PILLAR_KEYWORDS = {
    "procedure": [
        "regulatory reform", "regulatory relief", "regulatory sandbox",
        "regulatory cleanup", "red tape", "rulemaking", "deregulation",
        "deregulate", "permitting", "permit reform", "permitting reform",
        "occupational licens\\w*", "licensing reform", "licensing requirement\\w*",
        "administrative burden", "paperwork", "streamlin\\w*",
        "sunset review", "zoning reform", "housing permit\\w*",
        "regulatory simplification", "modernize regulations",
    ],
    "digital": [
        "information technology", "digital service\\w*", "digital government",
        "digital transformation", "digital ID", "modernization", "modernize",
        "broadband", "cybersecurity", "cyberattack", "ransomware",
        "data center\\w*", "artificial intelligence", "AI",
        "chief information officer", "CIO", "chief technology officer",
        "technology office", "online portal", "web portal", "state website",
        "legacy system\\w*", "IT system\\w*", "IT office", "IT project\\w*",
        "software", "automation", "data privacy", "e-government",
        "unemployment system", "benefits system", "eligibility system",
    ],
    "civil-service": [
        "civil service", "state employee\\w*", "state worker\\w*",
        "state workforce", "public employee\\w*", "public workforce",
        "hiring freeze", "layoff\\w*", "workforce reduction",
        "collective bargaining", "union contract", "merit system",
        "merit pay", "pay raise\\w*", "salary increase\\w*", "pay plan",
        "personnel", "vacanc\\w*", "retention", "telework", "remote work",
        "job classification\\w*", "reclassification", "pension reform",
        "workforce development", "hiring reform", "recruitment",
    ],
    # Incentives for outcomes (rubrics/rubric.md): the learning/feedback loop — funding,
    # oversight, and evaluation realigned toward whether programs actually work.
    # Covers outcome-tied funding, test-and-learn, accountability/transparency
    # dashboards, oversight, program evaluation, and legislative follow-up.
    "incentives": [
        "outcome-based funding", "outcomes-based funding", "performance-based funding",
        "outcome-contingent", "pay for success", "pay-for-performance",
        "performance management", "performance metric\\w*", "performance measure\\w*",
        "key performance indicator\\w*", "performance audit\\w*",
        "program evaluation", "program review\\w*", "outcome\\w* evaluation",
        "evidence-based", "data-driven", "results-based", "results-driven",
        "continuous improvement", "rapid-cycle", "feedback loop", "test-and-learn",
        "pilot program\\w*", "pilot project\\w*", "innovation fund\\w*",
        "accountability", "transparency dashboard", "accountability dashboard",
        "performance dashboard", "public dashboard", "data dashboard",
        "oversight", "legislative oversight", "oversight reform",
        "sunset provision\\w*", "measurable outcome\\w*", "track\\w* outcome\\w*",
    ],
}

PILLAR_PATTERNS = {
    pillar: re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)
    for pillar, words in PILLAR_KEYWORDS.items()
}

# Competency values (the dedupe stage's classify_event picks exactly one, incl.
# "none"). Mirrored in dedupe.py:PILLAR_CHOICES — keep the two in sync. The
# raw-article GATE 2 below screens for the four real capacities (incl. incentives);
# "none" is never a gate pass — it's only assigned later, per-event, in dedupe.py.
PILLAR_CHOICES = ["civil-service", "procedure", "digital", "incentives", "none"]
# Descriptive topic tags (rubrics/rubric.md). Mirrored in dedupe.py:TOPIC_TAG_CHOICES.
TOPIC_TAG_CHOICES = [
    "it-modernization", "ai", "data-privacy", "cybersecurity", "broadband",
    "benefits-systems", "procurement", "occupational-licensing", "permitting",
    "housing-land-use", "regulatory-reform", "hiring-recruitment",
    "compensation-pensions", "labor-relations", "telework-rto", "layoffs-rif",
    "reorganization", "transparency", "study-commission",
    "data-center", "tax-incentives", "energy-utility", "health-human-services",
    "higher-ed", "k12-education", "child-welfare",
]
ACTIVITY_TYPE_CHOICES = [
    "bill-introduced", "bill-passed", "veto", "EO", "rulemaking", "appointment",
    "reorg", "RFP/procurement", "budget", "program-launch", "audit/report",
]
SOURCE_TYPES = ["statenewsroom", "newspaper", "trade-press"]
ACTOR_TYPE_CHOICES = [
    "governor", "legislature", "state agency", "statewide official",
    "board/commission", "court", "university system", "other",
]

REQUIRED_FIELDS = [
    {"name": "Name", "type": "singleLineText"},
    {"name": "Notes", "type": "multilineText"},
    {"name": "event_id", "type": "singleLineText"},
    {"name": "date", "type": "date", "options": {"dateFormat": {"name": "iso"}}},
    {"name": "state", "type": "singleLineText"},
    {"name": "pillars", "type": "multipleSelects",
     "options": {"choices": [{"name": p} for p in PILLAR_CHOICES]}},
    # competency / relevance / topic_tags are written per-EVENT by dedupe.py
    # (clean "Events" table); declared here so the schema-of-record stays complete.
    # competency is multi-valued (an event can be e.g. both digital + incentives);
    # "none" is the empty list, so it's not a choice. Mirrors dedupe.COMPETENCY_CHOICES.
    {"name": "competency", "type": "multipleSelects",
     "options": {"choices": [{"name": p} for p in PILLAR_CHOICES if p != "none"]}},
    {"name": "topic_tags", "type": "multipleSelects",
     "options": {"choices": [{"name": t} for t in TOPIC_TAG_CHOICES]}},
    {"name": "relevance", "type": "number", "options": {"precision": 0}},
    {"name": "activity_type", "type": "singleSelect",
     "options": {"choices": [{"name": a} for a in ACTIVITY_TYPE_CHOICES]}},
    {"name": "gov_actor", "type": "singleLineText"},
    {"name": "headline", "type": "multilineText"},
    {"name": "why_it_matters", "type": "multilineText"},
    {"name": "source_urls", "type": "multilineText"},
    {"name": "source_outlets", "type": "singleLineText"},
    {"name": "status", "type": "singleLineText"},
    {"name": "source_type", "type": "singleSelect",
     "options": {"choices": [{"name": s} for s in SOURCE_TYPES]}},
    {"name": "actor_type", "type": "singleSelect",
     "options": {"choices": [{"name": a} for a in ACTOR_TYPE_CHOICES]}},
    # When WE scraped the row, as distinct from `date` (when the government
    # acted). dedupe.py windows on this: an article ingested today about a
    # six-week-old action has a six-week-old `date` and fell outside every
    # future window, so it never clustered. Mirrors candidates/pipeline.py.
    {"name": "ingested_at", "type": "dateTime",
     "options": {"dateFormat": {"name": "iso"},
                 "timeFormat": {"name": "24hour"},
                 "timeZone": "utc"}},
]

SYSTEM_PROMPT = """You classify news articles for the Recoding America State Capacity Tracker.
The input includes feed_state: the article's home state if it comes from a
state outlet, or "" if it comes from national trade press — in that case infer
the state from the article. If you cannot tell which state government acted,
fail gate 1. Apply two gates:

GATE 1 — PROVENANCE: Is the underlying activity an action by a STATE-level
government actor in their official capacity? State legislature, governor,
state agency or office, state board/commission.
  PASS examples: bill (introduced or passed), veto, executive order,
  rulemaking, appointment, agency reorg, RFP/procurement, budget move,
  program launch, official audit/report. A story about a state contract award
  PASSES because the award itself is a government action.
  FAIL examples: federal-government-only actions (a state implementing or
  responding to a federal action PASSES — the state response is the event),
  city/county-only actions, think-tank reports, advocacy, lawsuits by private
  parties, campaign coverage and promises, elections, punditry, opinion.

GATE 2 — PILLAR: Does it touch at least one of:
  - "procedure"     — Deproceduralization / Regulatory simplification
  - "digital"       — Digital & tech transformation
  - "civil-service" — Civil service & workforce reform
  - "incentives"    — Incentives for outcomes: the government's learning/feedback
                      loop — outcome-tied funding, oversight reform, program
                      evaluation, accountability/transparency dashboards,
                      test-and-learn pilots, legislative follow-up on existing law.
                      NOT a routine compliance audit or a substantive new mandate.

If BOTH gates pass, output ONLY this JSON object:
{
  "pass": true,
  "date": "YYYY-MM-DD date of the government action; use the publish date if unclear",
  "state": "2-letter code of the state whose government acted",
  "pillars": ["digital"],
  "activity_type": "one of: bill-introduced | bill-passed | veto | EO | rulemaking | appointment | reorg | RFP/procurement | budget | program-launch | audit/report",
  "gov_actor": "e.g., CO Office of Information Technology",
  "actor_type": "one of: governor | legislature | state agency | statewide official | board/commission | court | university system | other",
  "name": "concise title of the action, 5-10 words, no state name, sentence case",
  "headline": "one-line what happened, in your own words",
  "notes": "1-2 plain sentences: what happened and why it matters for state capacity",
  "why_it_matters": "one line, MAX 30 WORDS, written to the why_it_matters rules below",
  "status": "optional: introduced | enacted | etc., empty string if N/A"
}

Activity type guidance:
- 'veto' = a governor vetoing a bill (NOT 'EO'). 'EO' = executive orders only.
- A bill signed into law is 'bill-passed', not 'EO'.
- 'RFP/procurement' = purchases, contract awards, vendor selections.
- 'budget' = appropriations, pay-raise funding decisions, budget bills.
- 'rulemaking' = regulatory proceedings, rule adoption, regulatory approvals
  by boards/commissions.
- 'reorg' = restructuring, layoffs, buyouts, office eliminations.

Actor type guidance:
- 'governor' = governor/governor's office (incl. vetoes and EOs).
- 'legislature' = house/senate/general assembly and their committees.
- 'state agency' = executive departments and offices (DMV, OIT, DEP).
- 'statewide official' = AG, secretary of state, auditor, treasurer acting
  independently.
- 'board/commission' = boards of regents/education, PSC/PUC, ethics
  commissions, health plan boards.

If EITHER gate fails, output ONLY:
{"pass": false, "reason": "which gate failed and why, one short line"}

Output ONLY the JSON object. No markdown fences, no preamble, no trailing text.
""" + RULES


MAX_FEED_PAGES = 30


def parse_feed(url):
    """feedparser catches most errors into .bozo, but raw socket failures
    (e.g. a CDN dropping the connection, common from CI runner IPs) can
    still raise — one flaky outlet must never kill the run."""
    try:
        return feedparser.parse(url).entries
    except Exception as e:
        print(f"  fetch error {url}: {e}")
        return []


def fetch_feed(spec, min_date):
    """Fetch a feed, paging backwards through WordPress-style ?paged=N pages
    until entries are older than min_date. Many outlets expose only the
    newest ~10 items on page 1 (high-volume ones span barely an hour), so
    without pagination a weekly pull misses most of the week. Non-WordPress
    feeds ignore ?paged= and return duplicate entries, which ends the loop."""
    state, name, url, source_type = spec
    entries = parse_feed(url)
    if not entries:
        print(f"  FEED EMPTY/FAILED {name}")
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


def entry_date(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return date(t.tm_year, t.tm_mon, t.tm_mday)
    return None


def strip_html(text):
    return re.sub(r"<[^>]+>", " ", text or "")


def extract_article(spec, entry):
    state, name, url, source_type = spec
    pub = entry_date(entry)
    return {
        "state": state or "",
        "publisher": name,
        "source_type": source_type,
        "title": entry.get("title", ""),
        "published": pub.isoformat() if pub else "",
        "pub_date": pub,
        "url": entry.get("link", ""),
        "summary": strip_html(entry.get("summary", ""))[:1500].strip(),
    }


def prescreen(article):
    text = f"{article['title']} {article['summary']}"
    return [p for p, pat in PILLAR_PATTERNS.items() if pat.search(text)]


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
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Two JSON objects back to back make the slice above span both, and
        # json.loads reports "Extra data". Take the first complete object —
        # congress/llm.py has done this for a while; the other copies had not.
        obj, _ = json.JSONDecoder().raw_decode(text)
        return obj


def classify(client, article):
    user_msg = json.dumps({
        "feed_state": article["state"],
        "title": article["title"],
        "publisher": article["publisher"],
        "published": article["published"],
        "url": article["url"],
        "summary": article["summary"],
    })
    resp = client.messages.create(
        model=MODEL,
        max_tokens=700,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_msg}],
    )
    return parse_json_response(resp.content[0].text)


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
    """URLs already in the raw table, so re-runs skip ingested articles."""
    field = name_map.get("source_urls", "source_urls")
    urls = set()
    for rec in table.all(fields=[field]):
        for line in (rec["fields"].get(field) or "").splitlines():
            line = line.strip()
            if line:
                urls.add(line)
    return urls


def build_row(article, verdict, pillars, ingested_at):
    state = (verdict.get("state") or article["state"]).upper()[:2]
    short_name = (verdict.get("name") or verdict.get("headline") or article["title"]).strip()
    row = {
        "Name": f"{state} — {short_name}",
        "Notes": (verdict.get("notes") or "").strip(),
        "event_id": str(uuid.uuid4()),
        "state": state,
        "pillars": pillars,
        "gov_actor": verdict.get("gov_actor") or "",
        "headline": verdict.get("headline") or article["title"],
        "why_it_matters": verdict.get("why_it_matters") or "",
        "source_urls": article["url"],
        "source_outlets": article["publisher"],
        "status": verdict.get("status") or "",
        "source_type": article["source_type"],
        "date": article["published"],
        "ingested_at": ingested_at,
    }

    date_val = verdict.get("date") or ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_val):
        row["date"] = date_val

    activity = verdict.get("activity_type") or ""
    if activity in ACTIVITY_TYPE_CHOICES:
        row["activity_type"] = activity

    actor = verdict.get("actor_type") or ""
    row["actor_type"] = actor if actor in ACTOR_TYPE_CHOICES else "other"

    return row


def valid_pillars(verdict):
    pillars = verdict.get("pillars") or []
    if isinstance(pillars, str):
        pillars = [pillars]
    return [p for p in pillars if p in PILLAR_CHOICES]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("states", nargs="*", help="optional 2-letter state codes to limit the run")
    ap.add_argument("--days", type=int, default=7, help="lookback window in days (default 7)")
    ap.add_argument("--dry-run", action="store_true", help="classify but don't write to Airtable")
    ap.add_argument("--limit", type=int, default=0, help="cap articles sent to the classifier")
    args = ap.parse_args()

    min_date = date.today() - timedelta(days=args.days)

    feed_specs = list(sources.all_feeds())
    if args.states:
        wanted = {s.upper() for s in args.states}
        feed_specs = [f for f in feed_specs if f[0] is None or f[0] in wanted]

    print(f"Fetching {len(feed_specs)} feeds (window: since {min_date})...")
    articles = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        for spec, entries in ex.map(lambda s: fetch_feed(s, min_date), feed_specs):
            articles.extend(extract_article(spec, e) for e in entries)
    print(f"Got {len(articles)} entries\n")

    fresh = [a for a in articles if a["pub_date"] and a["pub_date"] >= min_date]
    print(f"Date gate (>= {min_date}): {len(fresh)} kept, {len(articles) - len(fresh)} dropped")

    screened = [a for a in fresh if prescreen(a)]
    print(f"Keyword pre-screen:        {len(screened)} kept, {len(fresh) - len(screened)} dropped")

    if args.limit and len(screened) > args.limit:
        screened = screened[:args.limit]
        print(f"--limit:                   capped at {args.limit}")

    if not screened:
        print("Nothing to classify.")
        return

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    table, name_map = None, {}
    if not args.dry_run:
        api = Api(AIRTABLE_TOKEN)
        table, name_map = ensure_table(api, AIRTABLE_BASE_ID, RAW_TABLE)
        seen = existing_source_urls(table, name_map)
        before = len(screened)
        screened = [a for a in screened if a["url"] not in seen]
        if before - len(screened):
            print(f"Already in Airtable:       {before - len(screened)} skipped")
        if not screened:
            print("Nothing new to classify.")
            return

    passed, dropped, errors = [], [], []
    done = 0

    print(f"\nClassifying {len(screened)} articles with {MODEL} "
          f"({CLASSIFY_WORKERS} workers)...")

    def work(article):
        return article, classify(client, article)

    with concurrent.futures.ThreadPoolExecutor(max_workers=CLASSIFY_WORKERS) as ex:
        futures = [ex.submit(work, a) for a in screened]
        for fut in concurrent.futures.as_completed(futures):
            done += 1
            try:
                a, verdict = fut.result()
            except Exception as e:
                errors.append(("?", f"classify: {e}"))
                print(f"  [{done}/{len(screened)}] ERROR — {e}")
                continue

            pillars = valid_pillars(verdict)
            if not verdict.get("pass") or not pillars:
                reason = verdict.get("reason") or "passed but no valid pillar"
                dropped.append((a, reason))
                print(f"  [{done}/{len(screened)}] DROP {a['state'] or '??'} — {reason[:70]}")
                continue

            passed.append((a, verdict, pillars))
            print(f"  [{done}/{len(screened)}] PASS "
                  f"{(verdict.get('state') or a['state'] or '??')[:2]} — "
                  f"{verdict.get('headline', '')[:70]}")

    written = 0
    if not args.dry_run and passed:
        ingested_at = datetime.now(timezone.utc).isoformat()
        print(f"\nWriting {len(passed)} rows to '{RAW_TABLE}'...")
        for a, verdict, pillars in passed:
            row = build_row(a, verdict, pillars, ingested_at)
            row = {name_map[k]: v for k, v in row.items() if k in name_map}
            try:
                table.create(row, typecast=True)
                written += 1
            except Exception as e:
                errors.append((a["title"], f"airtable: {e}"))
                print(f"  ERROR — airtable: {e}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Feeds:       {len(feed_specs)}")
    print(f"Entries:     {len(articles)}")
    print(f"In window:   {len(fresh)}")
    print(f"Classified:  {len(screened)}")
    print(f"Passed:      {len(passed)}")
    print(f"Dropped:     {len(dropped)}")
    print(f"Errors:      {len(errors)}")
    if not args.dry_run:
        print(f"Written:     {written}")
        print(f"\nNext: python dedupe.py --days {args.days}")

    if passed:
        print("\n--- PASSED ---")
        for a, v, pillars in sorted(passed, key=lambda x: ((x[1].get('state') or x[0]['state']), x[1].get('date') or '')):
            print(f"  {(v.get('state') or a['state'])[:2]} {v.get('date', a['published'])} "
                  f"[{','.join(pillars)}] {v.get('activity_type', '?')} — {v.get('headline', '')}")
            print(f"     src: {a['publisher']} ({a['source_type']})")

    if dropped:
        print("\n--- DROPPED (keyword hit, gates failed) ---")
        for a, reason in dropped:
            print(f"  {a['state'] or '??'} {a['title'][:70]}")
            print(f"     {reason}")

    if errors:
        print("\n--- ERRORS ---")
        for title, err in errors:
            print(f"  {title[:70]}: {err}")


if __name__ == "__main__":
    main()
