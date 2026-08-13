#!/usr/bin/env python3
"""Sync hearings and bills from Congress.gov into Airtable.

Unlike the press path, these need no clustering: one API record IS one hearing
or one bill, with a stable ID. They go straight to their tables and only need
a summary plus a competency tag. So there's no raw layer and no dedupe stage —
just fetch, classify, upsert.

Upsert (not the state pipeline's delete-then-rewrite) is what lets a reviewer's
review_status and reviewer_notes survive a nightly run.

Usage:
    python congress_api_sync.py --days 21
    python congress_api_sync.py --days 7 --hearings-only
    python congress_api_sync.py --days 21 --dry-run
    python congress_api_sync.py --days 21 --crosscheck   # HSGAC CMS vs. the API
"""

import argparse
import concurrent.futures
import os
import sys
from datetime import date, datetime, timedelta, timezone

from anthropic import Anthropic
from dotenv import load_dotenv
from pyairtable import Api

import congress_api
import congress_llm
import congress_schema as cs
import congress_sources
from airtable_util import ensure_table, upsert

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")

MODEL = "claude-sonnet-4-6"
WORKERS = 6

# The Congress.gov policyArea that maps onto federal capacity. Bills outside
# this set skip the LLM entirely — the same role the regex pre-screen plays in
# pipeline.py. Kept generous: the rubric does the real filtering.
CAPACITY_POLICY_AREAS = {
    "Government Operations and Politics",
    "Science, Technology, Communications",
    "Economics and Public Finance",
    "Labor and Employment",
    "Congress",
}

CLASSIFY_SYSTEM = congress_llm.RUBRIC_SYSTEM + """

---

# Output for this task

You are given ONE item (a hearing or a bill). Summarize it and classify it.

Output ONLY this JSON, no fences:
{
  "summary": "2-3 plain sentences: what this is and what it would actually do. No jargon, no press-release voice. For a hearing, what the committee is examining and why it was called.",
  "why_it_matters": "one line on the capacity angle for a RAF reader, or \\"\\" if the item is `none`",
  "competencies": ["digital"],
  "relevance": 3,
  "topic_tags": ["it-modernization"]
}

For a non-fit: {"summary": "...", "why_it_matters": "", "competencies": [], "relevance": 0, "topic_tags": []}
"""


def classify_all(client, payloads, label):
    return congress_llm.map_concurrent(
        lambda p: congress_llm.call(client, MODEL, CLASSIFY_SYSTEM, p),
        payloads, workers=WORKERS, label=f"classify {label}")


def apply_classification(row, verdict, summary_field="summary"):
    """Write the model's verdict onto a row, dropping unknown enum values.

    `summary_field` is explicit because hearings and bills name it differently
    (agenda_summary vs. summary). Inferring it from the keys already present
    silently routed every bill summary to a field the bills table doesn't
    have, where remap() dropped it.
    """
    if not verdict:
        return row
    row[summary_field] = verdict.get("summary") or row.get(summary_field) or ""
    row["why_it_matters"] = verdict.get("why_it_matters") or ""
    comps = cs.valid(verdict.get("competencies"), cs.COMPETENCY_CHOICES)
    row["competency"] = comps
    row["topic_tags"] = cs.valid(verdict.get("topic_tags"), cs.TOPIC_TAG_CHOICES)
    rel = cs.clamp_relevance(verdict.get("relevance"))
    # Relevance only means something alongside a competency — mirrors dedupe.py.
    row["relevance"] = rel if (comps and rel) else None
    return row


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Hearings
# ---------------------------------------------------------------------------
def _witnesses(meeting):
    """Witness names aren't a first-class field; they surface as witness
    documents and statements in meetingDocuments."""
    names = []
    for d in meeting.get("witnessDocuments") or []:
        n = (d.get("documentType") or "").strip()
        if n:
            names.append(n)
    for w in meeting.get("witnesses") or []:
        parts = [w.get("name"), w.get("position"), w.get("organization")]
        joined = ", ".join(p for p in parts if p)
        if joined:
            names.append(joined)
    return "\n".join(dict.fromkeys(names))


def _materials(meeting):
    urls = []
    for d in (meeting.get("meetingDocuments") or []) + (meeting.get("witnessDocuments") or []):
        u = d.get("url")
        if u:
            urls.append(u)
    for v in meeting.get("videos") or []:
        if v.get("url"):
            urls.append(v["url"])
    return "\n".join(dict.fromkeys(urls))


def _bill_refs(meeting):
    bills = ((meeting.get("relatedItems") or {}).get("bills")) or []
    return ", ".join(
        f"{b.get('type','')}{b.get('number','')}" for b in bills if b.get("number"))


def _hearing_status(meeting):
    s = (meeting.get("meetingStatus") or "").strip().lower()
    if s in ("scheduled",):
        return "scheduled"
    if s in ("canceled", "cancelled"):
        return "canceled"
    if s == "postponed":
        return "postponed"
    return "held"


def fetch_hearings(since, verbose=True):
    """List meetings updated since `since` in both chambers, fetch details,
    and keep those belonging to one of our seven committees."""
    kept = []
    for chamber in ("senate", "house"):
        try:
            listing = congress_api.list_meetings(chamber, since)
        except Exception as e:
            print(f"  meeting list failed ({chamber}): {e}")
            continue
        if verbose:
            print(f"  {chamber}: {len(listing)} meetings updated since {since}")

        def detail(m):
            try:
                return congress_api.get_meeting(chamber, m["eventId"])
            except Exception as e:
                print(f"  meeting detail failed {m.get('eventId')}: {e}")
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            details = list(ex.map(detail, listing))

        for m in details:
            if not m:
                continue
            codes = [c.get("systemCode") for c in (m.get("committees") or [])]
            key = next((congress_sources.CODE_TO_COMMITTEE[c]
                        for c in codes if c in congress_sources.CODE_TO_COMMITTEE), None)
            if key is None:
                continue
            kept.append((key, chamber, m))
    return kept


def build_hearing_rows(kept):
    rows, payloads = [], []
    for key, chamber, m in kept:
        event_id = str(m.get("eventId") or "")
        when = m.get("date") or ""
        loc = m.get("location") or {}
        location = ", ".join(p for p in [loc.get("building"), loc.get("room")] if p)
        title = (m.get("title") or "").strip()
        cname = congress_sources.COMMITTEES[key]["name"]
        rows.append({
            "Name": f"{key} — {title[:60]}" if title else f"{key} — meeting {event_id}",
            "hearing_key": f"{chamber}-{event_id}",
            "title": title,
            "hearing_date": when,
            "date": when[:10],
            "committee": key,
            "chamber": chamber,
            "location": location,
            "witnesses": _witnesses(m),
            "materials_urls": _materials(m),
            "bill_refs": _bill_refs(m),
            "meeting_type": m.get("type") or "",
            "hearing_status": _hearing_status(m),
            "source_urls": f"https://www.congress.gov/event/{congress_api.CURRENT_CONGRESS}"
                           f"th-congress/{chamber}-event/{event_id}",
            "review_status": "unreviewed",
            "synced_at": now_iso(),
        })
        payloads.append({
            "item_type": "congressional hearing or committee meeting",
            "committee": cname,
            "chamber": chamber,
            "meeting_type": m.get("type") or "",
            "date": when,
            "agenda_title": title,
            "bills_under_consideration": _bill_refs(m),
            "documents": [d.get("documentType") for d in (m.get("meetingDocuments") or [])][:12],
        })
    return rows, payloads


# ---------------------------------------------------------------------------
# Bills
# ---------------------------------------------------------------------------
def _bill_status(bill):
    text = ((bill.get("latestAction") or {}).get("text") or "").lower()
    if "became public law" in text or "signed by president" in text:
        return "enacted"
    if "vetoed" in text:
        return "vetoed"
    if "passed senate" in text and "passed house" in text:
        return "passed-both"
    if "passed" in text or "agreed to" in text:
        return "passed-chamber"
    if "reported" in text or "ordered to be reported" in text:
        return "reported"
    if "referred to" in text or "committee" in text:
        return "in-committee"
    return "introduced"


def fetch_bills(since, verbose=True):
    """For each committee, list referred/reported bills updated in the window,
    then fetch detail. Deduped across committees — a bill referred to two of
    our committees appears once."""
    seen, out = set(), []
    for key, c in congress_sources.COMMITTEES.items():
        try:
            listing = congress_api.list_committee_bills(c["chamber"], c["code"], since)
        except Exception as e:
            print(f"  bill list failed ({key}): {e}")
            continue
        if verbose:
            print(f"  {key:16} {len(listing)} bills")
        todo = []
        for b in listing:
            ident = (b.get("congress"), b.get("type"), b.get("number"))
            if not all(ident) or ident in seen:
                continue
            seen.add(ident)
            todo.append((key, ident))

        def detail(item):
            k, (cong, btype, num) = item
            try:
                return k, congress_api.get_bill(cong, btype, num)
            except Exception as e:
                print(f"  bill detail failed {btype}{num}: {e}")
                return k, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            out.extend([(k, b) for k, b in ex.map(detail, todo) if b])
    return out


def build_bill_rows(fetched):
    """Apply the policyArea pre-filter, then build rows + classifier payloads.
    Returns (rows, payloads, skipped_count)."""
    rows, payloads, skipped = [], [], 0
    for key, b in fetched:
        area = (b.get("policyArea") or {}).get("name") or ""
        if area and area not in CAPACITY_POLICY_AREAS:
            skipped += 1
            continue
        cong = b.get("congress")
        btype = (b.get("type") or "").upper()
        num = b.get("number")
        sponsors = b.get("sponsors") or [{}]
        sponsor = sponsors[0]
        action = b.get("latestAction") or {}
        bill_number = f"{btype} {num}"
        rows.append({
            "Name": f"{bill_number} — {(b.get('title') or '')[:60]}",
            "bill_id": f"{cong}-{btype}-{num}",
            "bill_number": bill_number,
            "congress": cong,
            "title": b.get("title") or "",
            "date": (action.get("actionDate") or b.get("introducedDate") or "")[:10],
            "introduced_date": (b.get("introducedDate") or "")[:10],
            "committee": key,
            "chamber": congress_sources.COMMITTEES[key]["chamber"],
            "sponsor": sponsor.get("fullName") or "",
            "sponsor_party": sponsor.get("party") or "",
            "cosponsor_count": (b.get("cosponsors") or {}).get("count") or 0,
            "latest_action": action.get("text") or "",
            "latest_action_date": (action.get("actionDate") or "")[:10],
            "bill_status": _bill_status(b),
            "policy_area": area,
            "source_urls": b.get("legislationUrl")
                           or f"https://www.congress.gov/bill/{cong}th-congress/"
                              f"{'senate-bill' if btype == 'S' else 'house-bill'}/{num}",
            "review_status": "unreviewed",
            "synced_at": now_iso(),
        })
        payloads.append({
            "item_type": "bill referred to or reported by a congressional committee",
            "bill_number": bill_number,
            "title": b.get("title") or "",
            "policy_area": area,
            "sponsor": sponsor.get("fullName") or "",
            "committee": congress_sources.COMMITTEES[key]["name"],
            "introduced": b.get("introducedDate") or "",
            "latest_action": action.get("text") or "",
        })
    return rows, payloads, skipped


def attach_crs_summaries(rows):
    """Fetch each bill's CRS summary and write it onto the row. One extra API
    call per bill; trivial against a 20,000/hour limit. Returns how many rows
    got one."""
    def fetch(row):
        try:
            cong, btype, num = row["bill_id"].split("-")
            return congress_api.get_bill_summary(int(cong), btype, num)
        except Exception:
            return ""

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        summaries = list(ex.map(fetch, rows))
    for row, s in zip(rows, summaries):
        # Long CRS text is a wall in the UI; the generated summary leads there.
        row["crs_summary"] = s[:1200]
    return sum(1 for s in summaries if s)


# ---------------------------------------------------------------------------
# HSGAC cross-check
# ---------------------------------------------------------------------------
def crosscheck_hsgac(since):
    """Does HSGAC's own CMS carry hearings Congress.gov doesn't, or carry them
    sooner? Compares on HEARING date (ACF hearing_date_time on the CMS side,
    `date` on the API side) — comparing the CMS *post* date against the API
    hearing date just measures notice lead time and looks like a discrepancy.

    Also reports notice lead: post date vs. hearing date on the CMS record.
    """
    import requests
    from congress_fetch import HEADERS, strip_html

    c = congress_sources.CROSSCHECK_WP_HEARINGS
    url = (f"{c['base']}/{c['post_type']}?after={since.isoformat()}T00:00:00"
           f"&per_page=100&orderby=date&order=desc")
    try:
        posts = requests.get(url, headers=HEADERS, timeout=30).json()
    except Exception as e:
        print(f"CMS fetch failed: {e}")
        posts = []

    cms = {}
    for p in posts:
        acf = p.get("acf") or {}
        hd = (acf.get("hearing_date_time") or "")[:10]
        if hd:
            cms[hd] = (strip_html(p.get("title", {}).get("rendered", "")),
                       (p.get("date") or "")[:10])

    api = {}
    for k, ch, m in fetch_hearings(since, verbose=False):
        if k == "hsgac":
            api[(m.get("date") or "")[:10]] = (m.get("title") or "")[:70]

    print(f"\nHSGAC hearings since {since}, compared on HEARING date\n")
    print(f"  {'hearing':<12} {'CMS':<5} {'API':<5} {'notice lead':<12} title")
    for d in sorted(set(cms) | set(api), reverse=True):
        in_cms, in_api = d in cms, d in api
        lead = ""
        if in_cms:
            posted = cms[d][1]
            if posted:
                lead = f"{(date.fromisoformat(d) - date.fromisoformat(posted)).days}d"
        title = (cms[d][0] if in_cms else api[d])[:52]
        print(f"  {d:<12} {'yes' if in_cms else '—':<5} {'yes' if in_api else '—':<5} "
              f"{lead:<12} {title}")

    only_cms = sorted(set(cms) - set(api))
    only_api = sorted(set(api) - set(cms))
    print(f"\n  CMS-only: {only_cms or 'none'}")
    print(f"  API-only: {only_api or 'none'}")
    if not only_cms:
        print("\n  => Congress.gov covers everything the committee CMS has.")
        print("     The CMS hearings endpoint stays out of the pipeline; the notice-lead")
        print("     column above is the only reason to revisit that.")


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--hearings-only", action="store_true")
    ap.add_argument("--bills-only", action="store_true")
    ap.add_argument("--crosscheck", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, help="cap items sent to the classifier")
    args = ap.parse_args()

    if not congress_api.have_key():
        # A clean skip, not a failure — the press pipeline must still run in CI.
        print("CONGRESS_API_KEY not set — skipping hearings and bills sync.")
        print("Add it to .env locally and to the repo's GitHub Actions secrets.")
        return 0

    since = date.today() - timedelta(days=args.days)

    if args.crosscheck:
        crosscheck_hsgac(since)
        return 0

    missing = [k for k, v in {"ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
                              "AIRTABLE_TOKEN": AIRTABLE_TOKEN,
                              "AIRTABLE_BASE_ID": AIRTABLE_BASE_ID}.items() if not v]
    if missing:
        sys.exit(f"Missing env vars: {', '.join(missing)}")

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    api = Api(AIRTABLE_TOKEN)
    do_hearings = not args.bills_only
    do_bills = not args.hearings_only

    if do_hearings:
        print(f"\n=== Hearings (window >= {since}) ===")
        kept = fetch_hearings(since)
        print(f"  {len(kept)} in our seven committees")
        rows, payloads = build_hearing_rows(kept)
        if args.limit:
            rows, payloads = rows[:args.limit], payloads[:args.limit]
        verdicts = classify_all(client, payloads, "hearing")
        for row, v in zip(rows, verdicts):
            apply_classification(row, v, "agenda_summary")
        hit = sum(1 for r in rows if r.get("competency"))
        print(f"  {hit}/{len(rows)} matched a competency")
        for r in sorted(rows, key=lambda x: -(x.get("relevance") or 0))[:10]:
            comp = ",".join(r.get("competency") or []) or "none"
            print(f"    [{comp} {r.get('relevance') or '-'}] {r['date']} "
                  f"{r['committee']}: {(r['title'] or '')[:70]}")
        if args.dry_run:
            print("  (dry run — nothing written)")
        else:
            table, name_map = ensure_table(api, AIRTABLE_BASE_ID,
                                           cs.HEARINGS_TABLE, cs.HEARING_FIELDS)
            created, updated = upsert(table, name_map, rows, "hearing_key",
                                      preserve=cs.REVIEW_FIELDS)
            print(f"  wrote {created} new, {updated} updated -> {cs.HEARINGS_TABLE}")

    if do_bills:
        print(f"\n=== Bills (window >= {since}) ===")
        fetched = fetch_bills(since)
        rows, payloads, skipped = build_bill_rows(fetched)
        print(f"  {len(fetched)} fetched, {skipped} dropped on policy area, "
              f"{len(rows)} to classify")
        if args.limit:
            rows, payloads = rows[:args.limit], payloads[:args.limit]
        verdicts = classify_all(client, payloads, "bill")
        for row, v in zip(rows, verdicts):
            apply_classification(row, v)
        with_crs = attach_crs_summaries(rows)
        print(f"  {with_crs}/{len(rows)} have a CRS summary on Congress.gov")
        hit = sum(1 for r in rows if r.get("competency"))
        print(f"  {hit}/{len(rows)} matched a competency")
        for r in sorted(rows, key=lambda x: -(x.get("relevance") or 0))[:10]:
            comp = ",".join(r.get("competency") or []) or "none"
            print(f"    [{comp} {r.get('relevance') or '-'}] {r['bill_number']}: "
                  f"{(r['title'] or '')[:66]}")
        if args.dry_run:
            print("  (dry run — nothing written)")
        else:
            table, name_map = ensure_table(api, AIRTABLE_BASE_ID,
                                           cs.BILLS_TABLE, cs.BILL_FIELDS)
            created, updated = upsert(table, name_map, rows, "bill_id",
                                      preserve=cs.REVIEW_FIELDS)
            print(f"  wrote {created} new, {updated} updated -> {cs.BILLS_TABLE}")

    print(f"\nrate limit remaining: {congress_api.remaining()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
