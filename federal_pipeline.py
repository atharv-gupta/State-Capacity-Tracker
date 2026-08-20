#!/usr/bin/env python3
"""Federal executive-branch tracker — ingest (raw layer).

Pulls every source in federal_sources.py, keeps items from the last N days,
runs a two-gate Haiku classifier built around the INSTRUMENT TEST, and writes
one row per surviving ITEM to 'Federal Raw'.

federal_dedupe.py then clusters raw rows into one row per EVENT in
'Federal Events' — which matters more here than on any other tracker, because
one OMB memo is routinely covered by FedScoop, Nextgov, GovExec, Federal News
Network and The Hill on the same afternoon.

Where the keyword pre-screen applies, and why it doesn't apply everywhere:

  news lane          pre-screened. ~1,900 Hill posts per 3-week window makes
                     this the only lane where the LLM cost is real. Sources
                     flagged `broad` must ALSO hit a machinery anchor: the
                     capacity vocabulary alone matches half of general
                     political coverage on words like "oversight" and "AI".
  executive-action   NOT pre-screened. ~10 items a window, and the whole point
                     of the lane is that a bland OPM headline can hide a
                     governmentwide instrument. Paying for the gate is cheaper
                     than a keyword list that has to anticipate agency prose.
  rulemaking         NOT pre-screened. The Federal Register queries in
                     federal_sources.py ARE the pre-screen — they already scope
                     to machinery agencies, presidential documents and a
                     capacity vocabulary. Screening the result again on the
                     same words would only drop items whose relevance lives in
                     the abstract rather than the title.

Usage:
    python federal_pipeline.py                          # last 7 days
    python federal_pipeline.py --days 21                # backfill
    python federal_pipeline.py --days 21 --dry-run      # per-source funnel, no writes
    python federal_pipeline.py --lane executive-action  # one lane
    python federal_pipeline.py --source hill --limit 20
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

import federal_llm
import federal_fetch
import federal_schema as fs
import federal_sources
from airtable_util import ensure_table, remap
from congress_pipeline import PILLAR_KEYWORDS as _CONGRESS_KEYWORDS

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")

MODEL = federal_llm.MODEL_GATE
FETCH_WORKERS = 10
CLASSIFY_WORKERS = 8
HYDRATE_CAP = 60          # agency-page article fetches per run; see hydrate()

# ---------------------------------------------------------------------------
# Keyword pre-screen. The congressional lists were already written for federal
# capacity vocabulary, so they are imported rather than copied — one list to
# maintain, and a term added for one tracker helps the other. The additions
# below are the executive-branch instruments the congressional lists have no
# reason to carry.
# ---------------------------------------------------------------------------
EXTRA_KEYWORDS = {
    "civil-service": [
        "staffing plan\\w*", "workforce plan\\w*", "position classification",
        "\\bSF-?50\\b", "personnel record\\w*", "suitability determination\\w*",
        "\\bTSP\\b", "\\bFEHB\\b", "federal retirement", "\\bFERS\\b",
        "excepted service", "competitive service", "\\bpay agent\\b",
        "performance management", "workforce reshaping",
    ],
    "procedure": [
        "\\bM-2\\d-\\d\\d\\b", "OMB memo\\w*", "circular a-\\d+",
        "information collection\\w*", "\\bICR\\b", "burden hour\\w*",
        "unified agenda", "regulatory agenda", "\\bFAR\\b council",
        "federal acquisition regulation", "acquisition regulation",
        "delegation of authority", "policy letter", "governmentwide guidance",
        "federal register notice", "notice of proposed rulemaking", "\\bNPRM\\b",
    ],
    "digital": [
        "\\bIT\\b portfolio", "system of records", "\\bAPI\\b", "shared service\\w*",
        "digital experience", "customer experience", "\\bCX\\b",
        "zero trust", "post-quantum", "cryptograph\\w*", "logging requirement\\w*",
        "electronic health record\\w*", "\\bEHR\\b", "modernization contract\\w*",
        "software license\\w*", "\\bSaaS\\b", "data center consolidation",
    ],
    "incentives": [
        "priority goal\\w*", "agency priority goal\\w*", "\\bAPG\\b",
        "annual performance plan", "performance.gov", "evidence-building",
        "learning agenda", "payment integrity", "\\bDATA Act\\b",
        "recovery audit\\w*", "corrective action plan\\w*",
    ],
}

PILLAR_KEYWORDS = {
    pillar: _CONGRESS_KEYWORDS[pillar] + EXTRA_KEYWORDS[pillar]
    for pillar in _CONGRESS_KEYWORDS
}

PILLAR_PATTERNS = {
    pillar: re.compile("|".join(f"(?:{w})" for w in words), re.IGNORECASE)
    for pillar, words in PILLAR_KEYWORDS.items()
}

# ---------------------------------------------------------------------------
# Machinery anchor. Required IN ADDITION to a capacity keyword for outlets
# flagged `broad` in the registry (The Hill). The capacity lists contain words
# that general political coverage uses constantly — "oversight",
# "accountability", "transparency", "AI", "automation" — so on a 100-post-a-day
# general-news feed they are close to a no-op. This list is institutions and
# instruments: things that only appear when the subject really is the machinery
# of the federal government.
# ---------------------------------------------------------------------------
ANCHOR_WORDS = [
    "\\bOPM\\b", "office of personnel management", "\\bOMB\\b",
    "office of management and budget", "\\bGSA\\b", "general services administration",
    "\\bOIRA\\b", "\\bMSPB\\b", "\\bFLRA\\b", "\\bGAO\\b", "\\bCISA\\b",
    "\\bUSDS\\b", "\\bDOGE\\b", "inspector general", "\\bOffice of Government Ethics\\b",
    "federal employee\\w*", "federal worker\\w*", "federal workforce",
    "civil service", "civil servant\\w*", "merit system",
    "schedule f", "senior executive service", "reduction in force", "\\bRIF\\b",
    "deferred resignation", "probationary employee\\w*", "collective bargaining",
    "federal agenc\\w+", "agency head\\w*", "executive order", "presidential memorand\\w+",
    "federal register", "rulemaking", "paperwork reduction",
    "federal contract\\w*", "federal procurement", "government shutdown",
    "\\bIT\\b modernization", "\\bFedRAMP\\b", "login.gov",
    "technology modernization fund", "government efficiency",
    "civil servants", "government employees", "\\bshutdown\\b",
]
ANCHOR_PATTERN = re.compile("|".join(f"(?:{w})" for w in ANCHOR_WORDS), re.IGNORECASE)


SYSTEM_PROMPT = f"""You screen federal executive-branch items for the Recoding America
Federal Capacity Tracker.

Recoding America works on four government-capacity competencies, applied here to the
FEDERAL EXECUTIVE BRANCH — how it builds and runs ITSELF, not what it regulates in
the wider economy. Apply two gates.

GATE 1 — THE INSTRUMENT TEST. Is there a concrete action, and can you name it?
An item passes only if you can point to one of these:
  a numbered OMB memorandum or circular; agency guidance, a policy letter, a
  directive or a delegation of authority; a proposed or final rule; a Federal
  Register notice with legal effect; an executive order or presidential
  memorandum; a workforce action actually taken (RIF, hiring authority,
  reclassification, pay determination, collective-bargaining order); a
  procurement action (solicitation, award, contract vehicle, acquisition-rule
  change); a system or service launched or shut down; a reorganization (office
  stood up, merged, moved, abolished); a report with findings, or a data
  release; a court order requiring an agency to act or stop.
FAIL Gate 1 for: ICYMI items, interviews, podcast episodes, op-eds, transcripts;
  statements praising, condemning or "responding to" someone; anniversaries,
  awards, commemorations; a named official simply arriving or departing;
  restatements of existing policy; announcements of intent to be more efficient
  with no mechanism; analysis, opinion and explainer pieces; vendor business
  news; a routine Paperwork Reduction Act collection renewal, standard meeting
  notice, Privacy Act system-of-records reprint, or technical correction.
A press release ABOUT a real instrument passes — the instrument is the event, even
if the framing is partisan. A release that is ONLY framing fails.
A GAO or inspector-general report satisfies Gate 1 by being published — these
bodies act by reporting. Do not reason that a research product is not an action,
and do not require that anyone has responded to it. (A routine data refresh or
manual revision with no findings is still a Gate 1 fail: nothing was examined.)
Trade-press reporting on a draft or unannounced action PASSES if the action is
specific; record it as `reported` or `draft-leaked` rather than dropping it.

GATE 2 — COMPETENCY. Does the underlying action touch at least one of:
  - "civil-service" — the federal workforce system: hiring, classification, pay,
    performance, removal, and where that authority sits (Schedule F, RIFs, OPM
    rules, SES, collective bargaining, merit protections, telework directives).
  - "procedure"     — the federal government's own procedural and compliance
    burden (Paperwork Reduction Act, OMB circulars, OIRA review, the rulemaking
    process, NEPA and permitting process, reporting mandates, grant
    administration, the FAR as process).
  - "digital"       — how the federal government builds, buys, staffs and
    oversees its OWN technology and data (IT modernization, TMF, FedRAMP, agency
    AI use and governance, cybersecurity of federal systems, benefits and claims
    systems, identity and Login.gov, federal data governance, IT acquisition).
  - "incentives"    — the federal learning loop: IG and GAO findings and their
    implementation, program evaluation, performance plans and measures,
    payment integrity, outcome-tied funding, working-capital fund mechanics.

IMPORTANT CALIBRATION:
- Most items FAIL. That is expected and correct. Do not stretch.
- Regulating an industry is not `procedure`; regulating private AI or private
  technology is not `digital`. The action must reach the government's OWN
  machinery. An OMB memo governing how agencies use AI is `digital`; a rule
  constraining private AI developers is a fail.
- A funding level, increase, cut, rescission or CR is NOT a competency by
  itself. Appropriations count only when the funding MODEL changes.
- A named official being hired or fired is not `civil-service`. The workforce
  SYSTEM changing is.
- Judge the underlying action, not the headline's framing.
- Strip promotional and partisan adjectives from everything you write. "Historic",
  "commonsense", "radical", "misguided", "restoring", "war on" are not facts.

If BOTH gates pass, output ONLY this JSON object:
{{
  "pass": true,
  "date": "YYYY-MM-DD of the action; use the publish date if unclear",
  "pillars": ["digital"],
  "branch": "whose machinery the action reaches, one of: {' | '.join(fs.BRANCH_CHOICES)}. For a GAO or inspector-general report this is the branch the report EXAMINES (usually 'executive'), not the branch the auditor sits in.",
  "agency": ["which agencies the action is BY or ABOUT, from: {', '.join(fs.AGENCY_CHOICES)}"],
  "instrument_type": "one of: {' | '.join(fs.INSTRUMENT_TYPE_CHOICES)}",
  "instrument_id": "the document's own identifier if there is one, e.g. 'M-26-15', 'EO 14170', '90 FR 33421', else \\"\\"",
  "verification": "one of: {' | '.join(fs.VERIFICATION_CHOICES)}",
  "actor": "who acted, e.g. 'OPM' or 'OMB' or 'GSA' or 'U.S. District Court, D.D.C.'",
  "name": "concise neutral title of the action, 5-10 words, sentence case",
  "headline": "one neutral line, your own words, what happened",
  "notes": "1-2 plain sentences: the mechanism, and why it matters for federal capacity",
  "document_url": "URL of the primary document if the item names one, else \\"\\"",
  "status": "optional stage note, e.g. 'proposed' or 'effective Oct 1', else \\"\\""
}}

If EITHER gate fails, output ONLY:
{{"pass": false, "reason": "which gate failed and why, one short line"}}

Output ONLY the JSON object. No markdown fences, no preamble, no trailing text.
"""


def prescreen(item, broad=False):
    """Return the pillars whose vocabulary the item hits, or [] to drop it.

    `broad` outlets must also hit a machinery anchor — see ANCHOR_PATTERN.
    """
    text = f"{item['title']} {item['body']}"
    hits = [p for p, pat in PILLAR_PATTERNS.items() if pat.search(text)]
    if broad and hits and not ANCHOR_PATTERN.search(text):
        return []
    return hits


def classify(client, item):
    return federal_llm.call(client, MODEL, SYSTEM_PROMPT, {
        "source": item["source"],
        "outlet": item["outlet"],
        "lane": item["lane"],
        "source_agency": item["agency"] or "(not agency-specific)",
        "instrument_hint": item.get("instrument_hint") or "",
        "title": item["title"],
        "published": item["published"],
        "url": item["url"],
        "body": item["body"][:4000],
    }, max_tokens=900)


def existing_source_urls(table, name_map):
    field = name_map.get("source_urls", "source_urls")
    urls = set()
    for rec in table.all(fields=[field]):
        for line in (rec["fields"].get(field) or "").splitlines():
            line = line.strip()
            if line:
                urls.add(line)
    return urls


def hydrate(items):
    """Fill in bodies that the listing pages didn't carry.

    Two mechanisms, both deliberately AFTER the pre-screen and the
    already-ingested check so we never pay for an item we won't classify:
      - WordPress lite fetches get their content from the API in batches.
      - Agency listing rows (OPM, GSA, OMB news) have no body at all, so the
        release page itself is fetched. Capped at HYDRATE_CAP because this is
        one HTTP request per item; a backfill that blows the cap classifies the
        rest on their titles, which are declarative on these sites.
    """
    federal_fetch.hydrate_wp([i for i in items if i.get("needs_hydrate")])
    needs_page = [i for i in items
                  if i["kind"] == "html" and not i["body"]
                  and not (i.get("document_url") or "").lower().endswith(".pdf")]
    if not needs_page:
        return
    if len(needs_page) > HYDRATE_CAP:
        print(f"  hydrate cap: fetching {HYDRATE_CAP} of {len(needs_page)} agency pages")
        needs_page = needs_page[:HYDRATE_CAP]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for item, text in zip(needs_page,
                              ex.map(lambda i: federal_fetch.fetch_article_text(i["url"]),
                                     needs_page)):
            if text:
                item["body"] = text


def _document_url(item, verdict):
    doc = (verdict.get("document_url") or item.get("document_url") or "").strip()
    if item["lane"] == "news" and doc == item["url"]:
        return ""
    return doc[:500]


def build_row(item, verdict, pillars):
    name = (verdict.get("name") or verdict.get("headline") or item["title"]).strip()
    date_val = verdict.get("date") or ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_val):
        date_val = item["published"]
    instrument = verdict.get("instrument_type")
    branch = verdict.get("branch")
    # The model may name agencies the source spec already knows about; union
    # them so a GSA release always carries `gsa` even if the model only listed
    # the agency the action affects.
    agencies = fs.valid(verdict.get("agency"), fs.AGENCY_CHOICES)
    if item["agency"] and item["agency"] in fs.AGENCY_CHOICES and item["agency"] not in agencies:
        agencies.append(item["agency"])
    label = item["agency"] or item["outlet"]
    return {
        "Name": f"{label} — {name}"[:250],
        "headline": verdict.get("headline") or "",
        "notes": verdict.get("notes") or "",
        "date": date_val,
        "lane": item["lane"],
        "branch": branch if branch in fs.BRANCH_CHOICES else "executive",
        "agency": agencies,
        "instrument_type": instrument if instrument in fs.INSTRUMENT_TYPE_CHOICES else None,
        "instrument_id": (verdict.get("instrument_id") or item.get("instrument_hint") or "")[:120],
        "verification": (verdict.get("verification")
                         if verdict.get("verification") in fs.VERIFICATION_CHOICES
                         else ("official" if item["lane"] != "news" else "reported")),
        "pillars": pillars,
        "actor": (verdict.get("actor") or "")[:200],
        "source": item["source"],
        "source_kind": item["kind"],
        "source_urls": item["url"],
        # The primary document is what a reviewer clicks to check the framing
        # against the instrument. For a Federal Register document or an agency
        # release the item IS that document; for a news story it has to be a
        # different URL, or the column just repeats the article link.
        "document_url": _document_url(item, verdict),
        "status": (verdict.get("status") or "")[:100],
        "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--lane", help="news | executive-action | rulemaking")
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
    specs = [(lane, s) for lane, s in federal_sources.all_federal_sources()
             if (not args.lane or lane == args.lane)
             and (not args.source or args.source.lower() in s["name"].lower())]
    print(f"Fetching {len(specs)} sources, window >= {min_date}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        fetched = list(ex.map(
            lambda ls: (ls[1]["name"], federal_fetch.fetch_source(ls[0], ls[1], min_date)),
            specs))

    # Per-source funnel. This table is the diagnostic that separates "this
    # source was quiet" from "this parser broke" — several of these sources go
    # weeks without a qualifying item, and OMB's newsroom can go months.
    funnel, items, spec_by_name = {}, [], {s["name"]: s for _, s in specs}
    for name, got in fetched:
        broad = bool(spec_by_name[name].get("broad"))
        kept = [i for i in got if not i["pub_date"] or i["pub_date"] >= min_date]
        # Only the news lane is pre-screened; see the module docstring.
        if kept and kept[0]["lane"] == "news":
            screened = [i for i in kept if prescreen(i, broad=broad)]
        else:
            screened = kept
        funnel[name] = {"fetched": len(got), "window": len(kept), "screened": len(screened)}
        items.extend(screened)

    # One Federal Register document matches several term queries, and one story
    # can appear in two feeds of the same outlet. Collapse on URL before paying
    # for anything downstream.
    seen_run, unique = set(), []
    for i in items:
        if i["url"] and i["url"] in seen_run:
            continue
        seen_run.add(i["url"])
        unique.append(i)
    dupes = len(items) - len(unique)
    items = unique

    print(f"\n{sum(f['fetched'] for f in funnel.values())} fetched, "
          f"{sum(f['window'] for f in funnel.values())} in window, "
          f"{sum(f['screened'] for f in funnel.values())} kept by lane rules, "
          f"{dupes} cross-source duplicates, {len(items)} to classify")

    if not args.dry_run:
        table, name_map = ensure_table(Api(AIRTABLE_TOKEN), AIRTABLE_BASE_ID,
                                       fs.RAW_TABLE, fs.RAW_FIELDS)
        already = existing_source_urls(table, name_map)
        before = len(items)
        items = [i for i in items if i["url"] not in already]
        print(f"{before - len(items)} already ingested, {len(items)} new")
    else:
        table = name_map = None

    if args.limit:
        items = items[:args.limit]
    if not items:
        print("Nothing to classify.")
        return 0

    print("Hydrating bodies...")
    hydrate(items)

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    print(f"Classifying {len(items)} items with {MODEL}...")
    verdicts = federal_llm.map_concurrent(
        lambda it: classify(client, it), items,
        workers=CLASSIFY_WORKERS, label="gate")

    rows, passed, failed = [], 0, {}
    for item, verdict in zip(items, verdicts):
        if not verdict:
            funnel[item["source"]]["error"] = funnel[item["source"]].get("error", 0) + 1
            continue
        pillars = fs.valid(verdict.get("pillars"), fs.COMPETENCY_CHOICES)
        if not verdict.get("pass") or not pillars:
            reason = verdict.get("reason") or "passed but no valid pillar"
            failed[reason[:60]] = failed.get(reason[:60], 0) + 1
            continue
        passed += 1
        funnel[item["source"]]["passed"] = funnel[item["source"]].get("passed", 0) + 1
        rows.append(build_row(item, verdict, pillars))

    print(f"\n{passed}/{len(items)} passed both gates")
    print(f"\n{'fetched':>8} {'window':>7} {'kept':>6} {'pass':>5}  source")
    for name, f in sorted(funnel.items(), key=lambda kv: -kv[1]["fetched"]):
        print(f"{f['fetched']:8} {f['window']:7} {f['screened']:6} "
              f"{f.get('passed', 0):5}  {name}")

    if rows:
        print("\npassing items:")
        for r in sorted(rows, key=lambda x: x["date"], reverse=True):
            print(f"  {r['date']}  [{','.join(r['pillars'])}]  {r['lane']:16} "
                  f"{r['instrument_type'] or '?':22} {r['headline'][:66]}")

    if args.dry_run:
        print("\n(dry run — nothing written)")
        return 0

    for i in range(0, len(rows), 10):
        table.batch_create([remap(r, name_map) for r in rows[i:i + 10]], typecast=True)
    print(f"\nWrote {len(rows)} rows -> {fs.RAW_TABLE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
