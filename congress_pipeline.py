#!/usr/bin/env python3
"""Congressional tracker — press/activity ingest (raw layer).

Pulls every press source in congress_sources.py, keeps items from the last N
days, pre-screens on federal-capacity keywords, runs a two-gate Haiku
classifier, and writes one row per surviving ITEM to 'Congress Raw'.

congress_dedupe.py then clusters raw rows into one row per EVENT in
'Congress Events'. Hearings and bills do not come through here — see
congress_api_sync.py.

The gate that matters here is GATE 1. These feeds are largely partisan
messaging: a release reacting to the other party is not an event. Filtering
that out before the expensive Sonnet pass is most of the job.

Usage:
    python congress_pipeline.py                    # last 7 days
    python congress_pipeline.py --days 21          # backfill
    python congress_pipeline.py --dry-run          # classify, don't write
    python congress_pipeline.py --source hsgac     # substring match on name
    python congress_pipeline.py --limit 20
"""

import argparse
import concurrent.futures
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

from anthropic import Anthropic
from dotenv import load_dotenv
from pyairtable import Api

import congress_fetch
import congress_llm
import congress_schema as cs
import congress_sources
from airtable_util import ensure_table, remap

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")

MODEL = congress_llm.MODEL_GATE
FETCH_WORKERS = 12
CLASSIFY_WORKERS = 8

# ---------------------------------------------------------------------------
# Keyword pre-screen. Federal analogue of pipeline.PILLAR_KEYWORDS — same
# purpose (a cheap filter before any LLM call), different vocabulary: this is
# the language of federal government operations, not state government.
# Like the state lists, misses come from words missing here. Treat as living.
# ---------------------------------------------------------------------------
PILLAR_KEYWORDS = {
    "civil-service": [
        "federal employee\\w*", "federal worker\\w*", "federal workforce",
        "civil service", "civil servant\\w*", "merit system", "merit principle\\w*",
        "schedule f", "senior executive service", "\\bSES\\b",
        "reduction in force", "\\bRIF\\b", "\\bRIFs\\b", "reorganization plan",
        "hiring freeze", "hiring authority", "hiring reform", "direct hire",
        "\\bOPM\\b", "office of personnel management", "official time",
        "collective bargaining", "federal union\\w*", "probationary period",
        "general schedule", "\\bGS-\\d+", "locality pay", "pay freeze",
        "performance appraisal\\w*", "removal procedure\\w*", "adverse action\\w*",
        "\\bMSPB\\b", "merit systems protection", "workforce reduction",
        "deferred resignation", "buyout\\w*", "attrition", "federal retirement",
        "telework", "return to office", "return-to-office",
    ],
    "procedure": [
        "paperwork reduction", "administrative burden", "regulatory burden",
        "red tape", "deregulation", "deregulatory", "regulatory reform",
        "regulatory relief", "rulemaking", "notice and comment",
        "\\bAPA\\b", "administrative procedure act", "\\bOIRA\\b",
        "office of information and regulatory affairs", "\\bOMB\\b circular",
        "\\bNEPA\\b", "permitting reform", "environmental review",
        "categorical exclusion\\w*", "compliance cost\\w*", "reporting requirement\\w*",
        "streamlin\\w*", "duplicative", "duplication", "sunset provision\\w*",
        "congressional review act", "guidance document\\w*",
        "grant\\w* administration", "single audit", "uniform guidance",
        "floor procedure", "germaneness", "committee jurisdiction",
        "suspension of the rules", "closed rule", "open rule", "special rule",
    ],
    "digital": [
        "information technology", "\\bIT\\b modernization", "legacy system\\w*",
        "technology modernization fund", "\\bTMF\\b", "\\bFedRAMP\\b",
        "\\bFITARA\\b", "chief information officer", "\\bCIO\\b",
        "\\bUSDS\\b", "united states digital service", "\\b18F\\b",
        "digital service\\w*", "government website\\w*", "\\bLogin.gov\\b",
        "artificial intelligence", "\\bAI\\b", "algorithm\\w*", "automation",
        "cybersecurity", "\\bCISA\\b", "ransomware", "data breach",
        "data governance", "data sharing", "interoperab\\w*",
        "benefits system\\w*", "eligibility system\\w*", "claims backlog",
        "payment integrity", "identity verification", "cloud migration",
        "software procurement", "\\bIT\\b acquisition", "voter roll\\w*",
        "voter registration system\\w*", "election security", "election system\\w*",
        "\\bEAC\\b", "election assistance commission",
    ],
    "incentives": [
        # The bare "GAO" token is kept even though the GAO feed itself moved to
        # the federal tracker on 2026-08-20: committee letters TO GAO, and
        # committee releases citing a GAO finding, are congressional events and
        # this is what catches them.
        "oversight", "investigation", "subpoena", "document request",
        "inspector general", "\\bIG\\b report", "\\bGAO\\b",
        "government accountability office", "high-risk list",
        "priority recommendation\\w*", "open recommendation\\w*",
        "program evaluation", "performance measure\\w*", "performance metric\\w*",
        "evidence-based", "evidence act", "improper payment\\w*",
        "waste, fraud", "fraud and abuse", "cost savings", "duplication",
        "outcome-based", "outcomes-based", "performance-based",
        "pay for success", "pilot program\\w*", "demonstration project\\w*",
        "reauthoriz\\w*", "authorization\\w* lapsed", "unauthorized appropriation\\w*",
        "zero-based budget\\w*", "reprogramming", "transfer authority",
        "no-year", "multi-year funding", "working capital fund",
        "accountability", "transparency", "dashboard",
    ],
}

# No \b wrapper around the alternation: several entries carry their own
# anchors (\bGS-\d+, \bAI\b) and an outer \b would fight them.
PILLAR_PATTERNS = {
    pillar: re.compile("|".join(f"(?:{w})" for w in words), re.IGNORECASE)
    for pillar, words in PILLAR_KEYWORDS.items()
}


SYSTEM_PROMPT = f"""You screen congressional press items for the Recoding America Congressional Tracker.

Recoding America works on four government-capacity competencies, applied here to the
FEDERAL government — how it builds and runs ITSELF, not what it regulates in
the wider economy. Apply two gates.

GATE 1 — IS THERE AN ACTION?
Does this item describe a concrete congressional or federal action?
  PASS: a hearing scheduled or held, a markup, a bill introduced/reported/
  passed/enacted, an oversight letter or document demand sent, a subpoena
  issued, a report released (incl. GAO/CBO products), a nomination advanced or
  blocked, an appropriations decision, a committee rule adopted, an
  investigation opened.
  A GAO or CBO report satisfies Gate 1 by being published — these agencies act
  by reporting. Do not reason that a research product is not an action, and do
  not require that Congress has responded to it. (A routine manual revision or
  data refresh with no findings is still a Gate 1 fail: nothing was examined.)
  FAIL: reaction and response statements, praise or criticism of the other
  party, floor speeches with no underlying action, "X responds to Y",
  "X slams Y", ICYMI roundups, op-ed reprints, newsletters, district events,
  grant announcements for the member's home state or district, ceremonial and
  commemorative items, campaign content, personnel announcements for the
  member's own office.
A press release ABOUT a real action passes — the action is the event, even if
the framing is partisan. A press release that is ONLY framing fails.

GATE 2 — COMPETENCY. Does the underlying action touch at least one of:
  - "civil-service" — the federal workforce system: hiring, classification,
    pay, performance, removal, and where that authority sits (Schedule F, RIFs,
    OPM rules, SES, collective bargaining, merit protections).
  - "procedure"     — the federal government's own procedural and compliance
    burden (Paperwork Reduction Act, OIRA, rulemaking process, NEPA and
    permitting process, reporting mandates, grant administration), and
    legislative-branch procedure (chamber rules, floor process).
  - "digital"       — how the federal government builds, buys, staffs, and
    oversees its OWN technology and data (IT modernization, TMF, FedRAMP,
    agency AI use, cybersecurity of federal systems, benefits and claims
    systems, federal data governance). Election administration systems —
    voter rolls, election security, EAC — count here.
  - "incentives"    — the federal learning loop: congressional oversight of
    whether programs work, GAO/IG findings and their implementation, program
    evaluation, outcome-tied funding, authorization follow-up.
    NOT oversight that is purely about a scandal, a personality, or a partisan
    dispute with no examination of whether a program works.

IMPORTANT CALIBRATION:
- Most items FAIL. That is expected and correct. Do not stretch.
- A funding level, increase, or cut is NOT a competency by itself. Appropriations
  count only when the action changes the funding MODEL (flexibility, multi-year
  or no-year authority, outcome-contingency, account restructuring).
- Regulating an industry is not `procedure`; regulating private technology is
  not `digital`. The action must reach the government's own machinery.
- Judge the underlying action, not the headline's framing.

If BOTH gates pass, output ONLY this JSON object:
{{
  "pass": true,
  "date": "YYYY-MM-DD of the action; use the publish date if unclear",
  "pillars": ["digital"],
  "activity_type": "one of: {' | '.join(cs.ACTIVITY_TYPE_CHOICES)}",
  "actor": "who acted, e.g. 'Senate HSGAC' or 'Rep. Comer' or 'GAO'",
  "name": "concise title of the action, 5-10 words, sentence case",
  "headline": "one line, in your own words, what happened",
  "notes": "1-2 plain sentences: what happened and why it matters for federal capacity",
  "bill_refs": "bill numbers mentioned, e.g. 'S. 2732, H.R. 9725', or \\"\\"",
  "status": "optional stage note, e.g. 'introduced' or 'reported', else \\"\\""
}}

If EITHER gate fails, output ONLY:
{{"pass": false, "reason": "which gate failed and why, one short line"}}

Output ONLY the JSON object. No markdown fences, no preamble, no trailing text.
"""


def prescreen(item):
    text = f"{item['title']} {item['body']}"
    return [p for p, pat in PILLAR_PATTERNS.items() if pat.search(text)]


def classify(client, item):
    return congress_llm.call(client, MODEL, SYSTEM_PROMPT, {
        "source": item["source"],
        "committee": item["committee"],
        "party_source": item["party"],
        "title": item["title"],
        "published": item["published"],
        "url": item["url"],
        "body": item["body"][:4000],
    }, max_tokens=800)


def existing_source_urls(table, name_map):
    field = name_map.get("source_urls", "source_urls")
    urls = set()
    for rec in table.all(fields=[field]):
        for line in (rec["fields"].get(field) or "").splitlines():
            line = line.strip()
            if line:
                urls.add(line)
    return urls


def chamber_for(committee):
    if committee in congress_sources.COMMITTEES:
        return congress_sources.COMMITTEES[committee]["chamber"]
    return congress_sources.EXTRA_COMMITTEES.get(committee, {}).get("chamber", "n/a")


def build_row(item, verdict, pillars):
    name = (verdict.get("name") or verdict.get("headline") or item["title"]).strip()
    date_val = verdict.get("date") or ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_val):
        date_val = item["published"]
    activity = verdict.get("activity_type")
    return {
        "Name": f"{item['committee']} — {name}"[:250],
        "headline": verdict.get("headline") or "",
        "notes": verdict.get("notes") or "",
        "date": date_val,
        "committee": item["committee"],
        "chamber": chamber_for(item["committee"]),
        "party_source": item["party"],
        "activity_type": activity if activity in cs.ACTIVITY_TYPE_CHOICES else None,
        "pillars": pillars,
        "actor": (verdict.get("actor") or "")[:200],
        "source": item["source"],
        "source_kind": item["kind"],
        "source_urls": item["url"],
        "bill_refs": (verdict.get("bill_refs") or "")[:200],
        "status": (verdict.get("status") or "")[:100],
        "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--source", help="substring match on source name")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    missing = [k for k, v in {"ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
                              "AIRTABLE_TOKEN": AIRTABLE_TOKEN,
                              "AIRTABLE_BASE_ID": AIRTABLE_BASE_ID}.items() if not v]
    if missing:
        sys.exit(f"Missing env vars: {', '.join(missing)}. See .env_example.")

    min_date = date.today() - timedelta(days=args.days)
    specs = [(k, s) for k, s in congress_sources.all_congress_sources()
             if not args.source or args.source.lower() in s["name"].lower()]
    print(f"Fetching {len(specs)} sources, window >= {min_date}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        fetched = list(ex.map(
            lambda ks: (ks[1]["name"], congress_fetch.fetch_source(ks[0], ks[1], min_date)),
            specs))

    # Per-source funnel. This table is the diagnostic: it separates "this
    # committee was quiet" from "this scraper broke".
    funnel = {}
    items = []
    for name, got in fetched:
        kept = [i for i in got if not i["pub_date"] or i["pub_date"] >= min_date]
        screened = [i for i in kept if prescreen(i)]
        funnel[name] = {"fetched": len(got), "window": len(kept), "screened": len(screened)}
        items.extend(screened)

    print(f"\n{sum(f['fetched'] for f in funnel.values())} fetched, "
          f"{sum(f['window'] for f in funnel.values())} in window, "
          f"{len(items)} passed keyword pre-screen")

    if not args.dry_run:
        table, name_map = ensure_table(api_obj := Api(AIRTABLE_TOKEN),
                                       AIRTABLE_BASE_ID, cs.RAW_TABLE, cs.RAW_FIELDS)
        seen = existing_source_urls(table, name_map)
        before = len(items)
        items = [i for i in items if i["url"] not in seen]
        print(f"{before - len(items)} already ingested, {len(items)} new")
    else:
        table = name_map = None

    if args.limit:
        items = items[:args.limit]
    if not items:
        print("Nothing to classify.")
        return 0

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    print(f"Classifying {len(items)} items with {MODEL}...")
    verdicts = congress_llm.map_concurrent(
        lambda it: classify(client, it), items,
        workers=CLASSIFY_WORKERS, label="gate")

    rows, passed, failed = [], 0, {}
    for item, verdict in zip(items, verdicts):
        if not verdict:
            funnel[item["source"]].setdefault("error", 0)
            funnel[item["source"]]["error"] += 1
            continue
        pillars = cs.valid(verdict.get("pillars"), cs.COMPETENCY_CHOICES)
        if not verdict.get("pass") or not pillars:
            reason = verdict.get("reason") or "passed but no valid pillar"
            failed[reason[:60]] = failed.get(reason[:60], 0) + 1
            continue
        passed += 1
        funnel[item["source"]]["passed"] = funnel[item["source"]].get("passed", 0) + 1
        rows.append(build_row(item, verdict, pillars))

    print(f"\n{passed}/{len(items)} passed both gates")
    print(f"\n{'fetched':>8} {'window':>7} {'screen':>7} {'pass':>5}  source")
    for name, f in sorted(funnel.items(), key=lambda kv: -kv[1]["fetched"]):
        print(f"{f['fetched']:8} {f['window']:7} {f['screened']:7} "
              f"{f.get('passed', 0):5}  {name}")

    if rows:
        print("\npassing items:")
        for r in sorted(rows, key=lambda x: x["date"], reverse=True):
            print(f"  {r['date']}  [{','.join(r['pillars'])}]  "
                  f"{r['committee']}: {r['headline'][:74]}")

    if args.dry_run:
        print("\n(dry run — nothing written)")
        return 0

    for i in range(0, len(rows), 10):
        table.batch_create([remap(r, name_map) for r in rows[i:i + 10]], typecast=True)
    print(f"\nWrote {len(rows)} rows -> {cs.RAW_TABLE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
