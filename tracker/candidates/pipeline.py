#!/usr/bin/env python3
"""Gubernatorial Candidates Tracker — developments ingest pipeline.

A standalone sibling to the State Capacity Tracker pipeline (the main pipeline
deliberately excludes campaign coverage; this one exists for it). For every
active candidate in the 'Gov Candidates' Airtable table it pulls a Google News
RSS query, keeps items from the last N days, dedups by URL against the
'Candidate Developments' table (the RAW layer — one row per article), then runs
one two-gate LLM call per surviving item: keep only items that are (gate 1)
substantively about the candidate's GOVERNING AGENDA — pure horse-race coverage
(polls, fundraising, attacks, process) is dropped — AND (gate 2) touch at least
one of Recoding America's four competencies (rubrics/rubric.md, adapted: what a candidate SAYS or
PLANS counts). Most campaign coverage fails gate 2, which is the point.

candidates_dedupe.py then clusters these raw rows into one row per DEVELOPMENT
in the clean 'Candidate Events' table and re-scores them with the full rubric,
exactly as dedupe.py does for the main tracker.

Usage:
    python candidates_pipeline.py                # last 7 days, all candidates
    python candidates_pipeline.py --days 30      # seed backfill
    python candidates_pipeline.py --state CO     # one state
    python candidates_pipeline.py --dry-run      # classify but don't write
    python candidates_pipeline.py --limit N      # cap items sent to the LLM
"""

import argparse
import concurrent.futures
import json
import os
import re
import sys
import threading
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone

import feedparser
import requests
from anthropic import Anthropic
from googlenewsdecoder import gnewsdecoder
from dotenv import load_dotenv
from tracker.shared.wim import CANDIDATE_RULES
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
    sys.exit(f"Missing env vars: {', '.join(_missing)}. See .env_example.")

CANDIDATES_TABLE = "Gov Candidates"
DEVELOPMENTS_TABLE = "Candidate Developments"
MODEL = "claude-haiku-4-5"
CLASSIFY_WORKERS = 8
# Google News RSS returns ~100/query. The cap exists to bound a run, not to
# select: entries are date-sorted BEFORE it applies (see fetch_candidate_items),
# because Google orders by relevance and the old relevance-ordered [:30] was
# silently discarding 30% of the week — concentrated on exactly the
# highest-profile candidates, who are the ones that return a full 100.
PER_CANDIDATE_CAP = 100

# Body fetching. Google News gives us a headline and an opaque redirect token,
# never article text, so the classifier used to judge a ~85-character stub that
# merely restated the title. gnewsdecoder resolves the token to the publisher
# URL and we fetch the article itself.
BODY_WORKERS = 6
BODY_TIMEOUT = 20
BODY_CHARS = 6000     # plenty for a news article; keeps classify cost bounded
BODY_MIN_CHARS = 400  # below this, treat as a failed extraction, not a short story
HOST_DELAY = 1.0      # seconds between requests to the same host
UA = "Recoding America State Capacity Tracker (+atharv@recodingamerica.fund)"

COMPETENCY_CHOICES = ["civil-service", "procedure", "digital", "incentives"]
DEV_TYPE_CHOICES = [
    "policy-plan", "press-release", "speech-quote", "interview",
    "news-coverage", "official-action", "other",
]

POSTAL_TO_NAME = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

REQUIRED_FIELDS = [
    {"name": "Name", "type": "singleLineText"},
    {"name": "candidate", "type": "singleLineText"},
    {"name": "state", "type": "singleLineText"},
    {"name": "date", "type": "date", "options": {"dateFormat": {"name": "iso"}}},
    {"name": "dev_type", "type": "singleSelect",
     "options": {"choices": [{"name": d} for d in DEV_TYPE_CHOICES]}},
    {"name": "short_title", "type": "singleLineText"},
    {"name": "headline", "type": "multilineText"},
    {"name": "summary", "type": "multilineText"},
    {"name": "why_it_matters", "type": "multilineText"},
    {"name": "competency", "type": "multipleSelects",
     "options": {"choices": [{"name": c} for c in COMPETENCY_CHOICES]}},
    {"name": "relevance", "type": "number", "options": {"precision": 0}},
    {"name": "quote", "type": "multilineText"},
    {"name": "source_urls", "type": "multilineText"},
    {"name": "source_outlets", "type": "singleLineText"},
    {"name": "url", "type": "singleLineText"},
    {"name": "ingested_at", "type": "dateTime",
     "options": {"dateFormat": {"name": "iso"},
                 "timeFormat": {"name": "24hour"},
                 "timeZone": "utc"}},
]

SYSTEM_PROMPT = """You screen ONE news item about a 2026 gubernatorial candidate
for Recoding America's Gubernatorial Candidates Tracker. Recoding America works on
four state-capacity competencies; the tracker watches what candidates say, plan,
and do about how state government BUILDS AND RUNS ITSELF.

The `body_is` field tells you what evidence you have. When it says "full
article text", judge on the article. When it says "HEADLINE ONLY", the
publisher blocked our fetch and no article text exists — judge the headline on
its own merits and DO NOT reject for thin or missing content. "No substantive
content", "headline-only stub" and "appears to be a stub" are not valid reasons
in that case; decide from what the headline itself asserts, and reject only if
the headline's own subject fails a gate. A headline naming a concrete
governing action ("orders a pause on data center approvals", "pledges to
replace agency heads") passes gate 1 on its own.

Apply BOTH gates. keep=true ONLY if both pass; otherwise keep=false.

GATE 1 — GOVERNING AGENDA: the item is substantively about the named
candidate's governing agenda, record, or plans. That includes:
  - policy plans, platform planks, or issue positions;
  - candidate press releases or official statements with policy content;
  - speeches, debate answers, interviews, or op-eds with policy substance;
  - the candidate's actions in a current office (a sitting AG, governor, mayor,
    legislator acting) — these reveal how they would govern;
  - concrete commitments (e.g. a promised day-one executive order).
DROP (keep=false): pure horse-race — polls, fundraising, endorsements without
policy content, attack coverage about the opponent, ads, staffing/process,
event logistics, punditry about who will win; items that only mention the
candidate in passing; items about a different person.

GATE 2 — COMPETENCY: the item touches at least ONE of the four
state-capacity competencies below. These are about how a state government
builds and runs itself — its own workforce, processes, technology, learning
loops — NOT about regulating the wider economy or society. For candidates, a
stated plan/position counts the same as an enacted action. Direction is
irrelevant: a plan that would undermine a competency is still a strong example
of it. If the item is a real governing-agenda item but touches NONE of the four
(a healthcare plan, a tax plan, a general crime platform), it FAILS gate 2 —
keep=false. Most campaign coverage fails here; that is expected and correct.
A later dedupe+classify pass re-scores kept items with the full rubric, so
lean toward keep only when a competency is genuinely present.

- civil-service: how the state hires, classifies, pays, evaluates, promotes, or
  separates its own employees, or where that authority sits. (Workforce plans,
  merit/at-will reform, union stances about the STATE workforce, hiring pledges.)
  A state changing how IT approves, permits, licenses, sites or subsidises
  something is changing its OWN process, and counts — even though the thing
  being approved is private. "Pause state approvals of data centres", "condition
  a tax abatement on performance benchmarks", "speed up permitting" are
  procedure and/or incentives, NOT out-of-scope economic regulation. Only a rule
  aimed purely at private conduct, with no change to the state's own machinery,
  is out of scope.

- procedure: deliberate changes to procedural/compliance burden — regulatory
  reform, red-tape cutting, permitting and occupational-licensing reform,
  government-efficiency initiatives. (A substantive industry policy with an
  incidental form is NOT procedure.)
- digital: how the state builds, buys, staffs, or oversees its OWN technology,
  data, and AI — IT modernization, digital service teams, government AI use.
  (Regulating private-sector tech only is NOT digital.)
- incentives: the learning/feedback loop — outcome-based funding, KPIs and
  performance dashboards, test-and-learn pilots, oversight reform, follow-up on
  existing law.

relevance (a kept item always has >=1 competency): 3 = the development is
centrally about that competency (a regulatory-reform plan, a pledged
government-efficiency EO); 2 = clearly an instance but partial or one piece of
a broader plan; 1 = at the edge.

Output ONLY this JSON object (no fences, no preamble). If keep=true, competencies
MUST be non-empty (an empty list means the item failed gate 2 -> keep=false):
{
  "keep": true,
  "dev_type": "one of: policy-plan | press-release | speech-quote | interview | news-coverage | official-action | other",
  "short_title": "6-12 word title naming what this is, sentence case, no candidate name (the digest and the web row show this, not the headline)",
  "headline": "one plain sentence, your own words: what the candidate said/did",
  "summary": "2-3 sentences of substance",
  "why_it_matters": "one line, MAX 30 WORDS, written to the why_it_matters rules below",
  "competencies": ["procedure"],
  "relevance": 2,
  "quote": "a short verbatim candidate quote if one carries the story, else \\"\\""
}
If it fails EITHER gate: {"keep": false, "reason": "which gate failed, one short line"}
""" + CANDIDATE_RULES


# --- Helpers lifted from ecosystem_pipeline.py --------------------------------

def parse_feed(url):
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
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Two JSON objects back to back make the slice above span both, and
        # json.loads reports "Extra data". Take the first complete object —
        # congress/llm.py has done this for a while; the other copies had not.
        obj, _ = json.JSONDecoder().raw_decode(text)
        return obj


def ensure_table(api, base_id, table_name, fields):
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


def existing_source_urls(table, name_map):
    field = name_map.get("url", "url")
    urls = set()
    for rec in table.all(fields=[field]):
        val = (rec["fields"].get(field) or "").strip()
        if val:
            urls.add(val)
    return urls


# --- Candidate-specific stages -------------------------------------------------

def load_candidates(api, state_filter=None):
    """Active candidates from Gov Candidates (skip withdrawn/defeated)."""
    table = api.base(AIRTABLE_BASE_ID).table(CANDIDATES_TABLE)
    out = []
    for rec in table.all():
        f = rec["fields"]
        status = (f.get("status") or "").strip()
        if status in ("withdrawn", "defeated"):
            continue
        state = (f.get("state") or "").strip().upper()
        if state_filter and state != state_filter:
            continue
        name = (f.get("candidate") or "").strip()
        if not name or not state:
            continue
        out.append({
            "candidate": name,
            "state": state,
            "party": f.get("party") or "",
            "status": status,
            "role": f.get("current_role") or "",
            "news_query": (f.get("news_query") or "").strip(),
        })
    return out


def name_variants(name):
    """Exact-phrase forms worth searching for one candidate.

    The roster stores legal names; the press uses shorter ones. A middle
    initial alone costs real coverage — "Daniel J. McKee" returns a third of
    what "Dan McKee" does — so search the stored name OR the same name with any
    single-letter initials removed. Nicknames can't be derived and still need
    the per-candidate news_query override.
    """
    variants = [name]
    words = name.split()
    # Drop single-letter initials: "Fredrick J. Love" -> "Fredrick Love".
    stripped = " ".join(w for w in words if not re.fullmatch(r"[A-Za-z]\.?", w))
    if stripped and stripped not in variants:
        variants.append(stripped)
    # First + last: "Helena Buonanno Foulkes" -> "Helena Foulkes". Additive, so
    # a wrong guess on a compound surname costs a few off-target results the
    # gates already reject, not lost coverage.
    sw = stripped.split()
    if len(sw) > 2:
        short = f"{sw[0]} {sw[-1]}"
        if short not in variants:
            variants.append(short)
    return variants


def gnews_url(cand, days):
    if cand["news_query"]:
        q = cand["news_query"]
    else:
        state = POSTAL_TO_NAME.get(cand["state"], cand["state"])
        names = " OR ".join(f'"{v}"' for v in name_variants(cand["candidate"]))
        q = f"({names}) {state} governor"
    q = f"{q} when:{days}d"
    return ("https://news.google.com/rss/search?q="
            + urllib.parse.quote(q) + "&hl=en-US&gl=US&ceid=US:en")


def fetch_candidate_items(cand, days, min_date):
    entries = parse_feed(gnews_url(cand, days))
    # Date-sort before capping. Google News returns relevance-ordered results
    # with jumbled dates, so slicing the raw list took an arbitrary subset and
    # let an article enter the window days after publication.
    dated = [(entry_date(e), e) for e in entries]
    dated = [(d, e) for d, e in dated if d and d >= min_date]
    dated.sort(key=lambda de: de[0], reverse=True)
    items = []
    for pub, e in dated[:PER_CANDIDATE_CAP]:
        url = e.get("link", "")
        if not url:
            continue
        # Google News titles end with " - Outlet"
        title = e.get("title", "")
        outlet = ""
        if " - " in title:
            title, outlet = title.rsplit(" - ", 1)
        items.append({
            "candidate": cand["candidate"],
            "state": cand["state"],
            "party": cand["party"],
            "status": cand["status"],
            "role": cand["role"],
            "title": title.strip(),
            "outlet": outlet.strip() or (e.get("source", {}) or {}).get("title", ""),
            "published": pub.isoformat(),
            "pub_date": pub,
            "url": url,
            "summary": strip_html(e.get("summary", ""))[:1500].strip(),
            # Seeded with the Google News stub (title + outlet). enrich_bodies
            # replaces this with real article text where the publisher allows.
            "body": strip_html(e.get("summary", ""))[:1500].strip(),
            "body_source": "headline-only",
            "article_url": "",
        })
    return items


_host_last = {}
_host_lock = threading.Lock()


def _host_wait(host):
    """One request per host per HOST_DELAY, so a burst of same-outlet articles
    doesn't hammer a single publisher."""
    with _host_lock:
        prev = _host_last.get(host, 0.0)
        wait = prev + HOST_DELAY - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _host_last[host] = time.monotonic()


def extract_body(html):
    """Article text from a publisher page. Paragraph tags only — good enough
    across the outlet mix here, and it degrades to '' rather than to nav
    furniture when a page is script-rendered."""
    html = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", html)
    main = re.search(r"(?is)<article\b.*?</article>", html)
    if main:
        html = main.group(0)
    paras = re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", html)
    text = " ".join(strip_html(x) for x in paras)
    return re.sub(r"\s+", " ", text).strip()


def fetch_body(item):
    """Resolve the Google News token to a publisher URL and fetch the article.

    Sets body/body_source/article_url on the item. Failure is normal and not
    fatal: some publishers (The Hill, Politico) return 403 to any crawler, so
    those fall back to headline-only and the prompt is told so explicitly.
    """
    item["body_source"] = "headline-only"
    item["article_url"] = ""
    try:
        decoded = gnewsdecoder(item["url"], interval=0)
    except Exception:
        return item
    if not decoded or not decoded.get("status"):
        return item
    url = decoded.get("decoded_url") or ""
    if not url:
        return item
    item["article_url"] = url
    try:
        _host_wait(urllib.parse.urlparse(url).netloc)
        r = requests.get(url, headers={"User-Agent": UA}, timeout=BODY_TIMEOUT)
        if r.status_code != 200:
            return item
        body = extract_body(r.text)
    except Exception:
        return item
    if len(body) >= BODY_MIN_CHARS:
        item["body"] = body[:BODY_CHARS]
        item["body_source"] = "article"
    return item


def enrich_bodies(items):
    """Fetch article bodies in parallel. Runs AFTER the already-ingested filter
    so we only pay for items we are about to classify."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=BODY_WORKERS) as ex:
        list(ex.map(fetch_body, items))
    got = sum(1 for i in items if i["body_source"] == "article")
    print(f"Article bodies fetched:    {got}/{len(items)} "
          f"({len(items) - got} fall back to headline-only)")
    return items


def classify(client, item):
    user_msg = json.dumps({
        "candidate": item["candidate"],
        "state": item["state"],
        "party": item["party"],
        "current_role": item["role"],
        "candidacy_status": item["status"],
        "title": item["title"],
        "outlet": item["outlet"],
        "published": item["published"],
        "body": item["body"],
        "body_is": ("full article text" if item.get("body_source") == "article"
                    else "HEADLINE ONLY - no article text available"),
    })
    resp = client.messages.create(
        model=MODEL,
        max_tokens=800,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_msg}],
    )
    return parse_json_response(resp.content[0].text)


def build_row(item, verdict, ingested_at):
    comps = verdict.get("competencies") or []
    if isinstance(comps, str):
        comps = [comps]
    comps = [c for c in comps if c in COMPETENCY_CHOICES]
    dev_type = verdict.get("dev_type") or ""
    headline = (verdict.get("headline") or item["title"]).strip()
    # `headline` is a sentence by contract, so it cannot be a title. Every other
    # tracker carries a separate short_title and the digest reads that; without
    # one here the email printed 21-word titles. Falling back to the sentence
    # keeps a row usable when the model omits the field.
    short_title = (verdict.get("short_title") or "").strip() or headline
    surname = item["candidate"].split()[-1]
    row = {
        "Name": f"{item['state']} — {surname}: {headline}"[:255],
        "candidate": item["candidate"],
        "state": item["state"],
        "date": item["published"],
        "dev_type": dev_type if dev_type in DEV_TYPE_CHOICES else "other",
        "short_title": short_title[:120],
        "headline": headline,
        "summary": (verdict.get("summary") or "").strip(),
        "why_it_matters": (verdict.get("why_it_matters") or "").strip(),
        "quote": (verdict.get("quote") or "").strip(),
        # Link to the publisher where we resolved it. `url` below stays the
        # Google News token because the already-ingested check dedups on it;
        # source_urls is what the web tab and the digest actually link to, and
        # a Google interstitial is useless to a reader.
        "source_urls": item.get("article_url") or item["url"],
        "source_outlets": item["outlet"],
        "url": item["url"],
        "ingested_at": ingested_at,
    }
    if comps:
        row["competency"] = comps
        try:
            rel = int(verdict.get("relevance") or 0)
        except (TypeError, ValueError):
            rel = 0
        if rel in (1, 2, 3):
            row["relevance"] = rel
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--state", default="", help="only this postal code")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="cap items sent to the LLM")
    args = ap.parse_args()

    min_date = date.today() - timedelta(days=args.days)
    ingested_at = datetime.now(timezone.utc).isoformat()

    api = Api(AIRTABLE_TOKEN)
    candidates = load_candidates(api, args.state.upper() or None)
    if not candidates:
        sys.exit("No active candidates in 'Gov Candidates' — run candidates_seed.py first.")
    print(f"Fetching Google News for {len(candidates)} candidates "
          f"(window: since {min_date})...")

    items = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for batch in ex.map(lambda c: fetch_candidate_items(c, args.days, min_date), candidates):
            items.extend(batch)
    print(f"Got {len(items)} items in window\n")

    table, name_map = None, {}
    if not args.dry_run:
        table, name_map = ensure_table(api, AIRTABLE_BASE_ID, DEVELOPMENTS_TABLE, REQUIRED_FIELDS)
        seen = existing_source_urls(table, name_map)
        before = len(items)
        items = [i for i in items if i["url"] not in seen]
        if before - len(items):
            print(f"Already in Airtable:       {before - len(items)} skipped")

    if args.limit and len(items) > args.limit:
        items = items[:args.limit]
        print(f"--limit:                   capped at {args.limit}")

    if not items:
        print("Nothing new to classify.")
        return

    enrich_bodies(items)

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    kept, dropped, errors = [], [], []
    done = 0

    print(f"\nClassifying {len(items)} items with {MODEL} ({CLASSIFY_WORKERS} workers)...")

    def work(item):
        return item, classify(client, item)

    with concurrent.futures.ThreadPoolExecutor(max_workers=CLASSIFY_WORKERS) as ex:
        futures = [ex.submit(work, i) for i in items]
        for fut in concurrent.futures.as_completed(futures):
            done += 1
            try:
                item, verdict = fut.result()
            except Exception as e:
                errors.append(("?", f"classify: {e}"))
                print(f"  [{done}/{len(items)}] ERROR — {e}")
                continue
            comps_valid = [c for c in (verdict.get("competencies") or [])
                           if c in COMPETENCY_CHOICES]
            # Gate 2 enforced in code: a kept item must touch >=1 competency, or
            # it is horse-race / off-lens noise regardless of what the model said.
            if not verdict.get("keep") or not comps_valid:
                reason = verdict.get("reason") or (
                    "kept but no competency (gate 2)" if verdict.get("keep") else "gate failed")
                dropped.append((item, reason))
                print(f"  [{done}/{len(items)}] DROP {item['state']} {item['candidate'].split()[-1]:<12} — "
                      f"{reason[:55]}")
                continue
            kept.append((item, verdict))
            comps = ",".join(verdict.get("competencies") or []) or "-"
            print(f"  [{done}/{len(items)}] KEEP {item['state']} {item['candidate'].split()[-1]:<12} "
                  f"[{comps}] {(verdict.get('headline') or item['title'])[:55]}")

    written = 0
    if not args.dry_run and kept:
        print(f"\nWriting {len(kept)} rows to '{DEVELOPMENTS_TABLE}'...")
        for item, verdict in kept:
            row = build_row(item, verdict, ingested_at)
            row = {name_map[k]: v for k, v in row.items() if k in name_map}
            try:
                table.create(row, typecast=True)
                written += 1
            except Exception as e:
                errors.append((item["title"], f"airtable: {e}"))
                print(f"  ERROR — airtable: {e}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Candidates:  {len(candidates)}")
    print(f"Items:       {len(items)} classified")
    print(f"Kept:        {len(kept)}")
    print(f"Dropped:     {len(dropped)}")
    print(f"Errors:      {len(errors)}")
    if not args.dry_run:
        print(f"Written:     {written}")

    if kept:
        print("\n--- KEPT ---")
        for item, v in sorted(kept, key=lambda x: (x[0]["state"], x[0]["published"])):
            comps = ",".join(v.get("competencies") or []) or "-"
            print(f"  {item['published']} {item['state']} {item['candidate']}: "
                  f"[{comps}] {(v.get('headline') or '')[:70]}")

    if errors:
        print("\n--- ERRORS ---")
        for title, err in errors:
            print(f"  {str(title)[:60]}: {err}")


if __name__ == "__main__":
    main()
