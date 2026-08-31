#!/usr/bin/env python3
"""Federal (executive-branch) source registry.

Same contract as sources.py and congress_sources.py: hardcoded dicts, one
generator that flattens them, adding a source is an edit here plus a commit.

Three LANES, and the lane is a property of the SOURCE, not of the model's
judgement (see federal_schema.LANE_CHOICES):

  executive-action  agency primary sources — OPM, OMB, GSA. What the executive
                    branch actually did, in its own words.
  news              federal trade press + The Hill. Second-hand, but it is the
                    only layer that catches an action the agency didn't announce.
  rulemaking        Federal Register API. The legal record: proposed and final
                    rules, notices, and presidential documents.

Four source kinds:
  wp_api      WordPress REST (?after= server-side filtering, X-WP-TotalPages
              paging, full bodies). Every trade outlet that has one.
  rss         a working feed, for the two outlets with no API
  html        a server-rendered listing + a named parser in federal_fetch
  fedreg-api  one Federal Register query

Probed live on 2026-08-19; per-source notes record what each actually returned.

    python federal_sources.py          # print the registry
    python federal_sources.py --json   # machine-readable, for the web view
"""

import json
import sys

# ---------------------------------------------------------------------------
# LANE: news. Federal trade press, plus The Hill.
#
# `broad` marks an outlet whose beat is wider than the federal government. The
# keyword pre-screen requires a machinery ANCHOR for these (see
# federal_pipeline.ANCHOR_PATTERN) — without it, The Hill's ~100 posts a day of
# general political coverage swamp the gate on tokens like "oversight" and "AI".
#
# `lite_fields` fetches title+excerpt only, pre-screens on that, then hydrates
# full bodies for survivors alone. The Hill is 3.6MB per 100 posts with bodies
# and 62KB without, so the two-stage fetch is the difference between a usable
# backfill and a 40MB one.
# ---------------------------------------------------------------------------
NEWS_SOURCES = [
    {
        "name": "FedScoop", "outlet": "FedScoop", "kind": "wp_api",
        "base": "https://fedscoop.com/wp-json/wp/v2", "post_type": "posts",
        # 44 posts / 21 days. The /feed/ RSS holds only 10 items, so the API is
        # the only way to backfill more than a week.
    },
    {
        "name": "Federal News Network", "outlet": "Federal News Network", "kind": "wp_api",
        "base": "https://federalnewsnetwork.com/wp-json/wp/v2", "post_type": "posts",
        # 194 / 21 days across 2 pages. Mixes reporting with podcast episodes;
        # the gate drops the latter for having no underlying action.
    },
    {
        "name": "MeriTalk", "outlet": "MeriTalk", "kind": "wp_api",
        "base": "https://www.meritalk.com/wp-json/wp/v2", "post_type": "posts",
        # 4 / 21 days. Publishes rarely now — a zero here is their cadence, not
        # a broken fetcher. (Their RSS carries 135 items back to 2020.)
    },
    {
        "name": "Nextgov/FCW", "outlet": "Nextgov/FCW", "kind": "rss",
        "url": "https://www.nextgov.com/rss/all/",
        # No WordPress API and the feed ignores ?page=, so retention is the
        # ~25 items it carries (~7 days). Daily runs are what keep this whole.
    },
    {
        "name": "Government Executive", "outlet": "Government Executive", "kind": "rss",
        "url": "https://www.govexec.com/rss/all/",
        # Same platform and same ~7-day ceiling as Nextgov.
    },
    {
        "name": "Route Fifty", "outlet": "Route Fifty", "kind": "rss",
        "url": "https://www.route-fifty.com/rss/all/",
        # GovExec family, same platform and same ~7-day ceiling as Nextgov and
        # Government Executive: no WordPress API and the feed ignores ?page=.
        # Government-management beat, so on-topic density is high.
    },
    {
        "name": "Washington Technology", "outlet": "Washington Technology", "kind": "rss",
        "url": "https://washingtontechnology.com/rss/all/",
        # Also GovExec family. Federal IT contracting — lands mostly on the
        # digital and procurement side of the rubric.
    },
    {
        "name": "The Hill", "outlet": "The Hill", "kind": "wp_api",
        "base": "https://thehill.com/wp-json/wp/v2", "post_type": "posts",
        "broad": True, "lite_fields": True,
        # ~100 posts/day, all beats. Included because the user's read of federal
        # activity runs through Hill coverage of the Congress-executive fight;
        # the anchor pre-screen is what makes that affordable.
    },
]

# ---------------------------------------------------------------------------
# LANE: executive-action. Agency primary sources.
#
# None of the four has a working feed, so each has a named parser in
# federal_fetch.py — these listings are too individual for one selector config
# (dates live in body text, in a <time> attribute, or only in the URL slug).
# ---------------------------------------------------------------------------
AGENCY_SOURCES = [
    {
        "name": "OPM press releases", "agency": "opm", "kind": "html",
        "url": "https://www.opm.gov/news/news-releases/", "parser": "opm",
        # 77 items on page 1 (months of history). No RSS: /news/news-releases/rss/
        # 404s. Roughly half the volume is ICYMI/interview messaging that the
        # instrument test drops.
    },
    {
        "name": "OMB news", "agency": "omb", "kind": "html",
        "url": "https://www.whitehouse.gov/omb/news/", "parser": "omb_news",
        # 10 items reaching back to 2025 — near-dead as a news feed. Kept
        # because when OMB does post here it is usually consequential.
        # whitehouse.gov 403s wp-json, so this is scraped, not API'd.
    },
    {
        "name": "OMB memoranda", "agency": "omb", "kind": "html",
        "url": "https://www.whitehouse.gov/omb/information-for-agencies/memoranda/",
        "parser": "omb_memoranda",
        # The real OMB signal. M-26-15 (post-quantum cryptography), M-26-14
        # (agency logging), M-26-17 (rescission of M-23-13) are federal-capacity
        # instruments by construction — they bind every agency. The listing
        # links straight to PDFs and the publication month is in the upload
        # path, which is the only date available.
    },
    {
        "name": "GSA news releases", "agency": "gsa", "kind": "html",
        "url": "https://www.gsa.gov/about-gsa/newsroom/news-releases", "parser": "gsa",
        # 65 releases in a table layout. The only date is the MMDDYYYY suffix on
        # the URL slug.
    },
]

# ---------------------------------------------------------------------------
# LANE: oversight. GAO.
#
# GAO used to live on the Congress tab, on the reasoning that it is Congress's
# watchdog. In practice that failed twice over: the trade press covers GAO
# heavily, so the reports arrived here anyway through FedScoop and Federal News
# Network (5 of 6 GAO-actor federal events in the first window restated a
# Congress Events row), and nothing deduplicated across the two trackers. GAO
# now belongs to this tracker, where its reports and the coverage of them
# cluster into one event. CBO stays on the Congress tab.
#
# Its own lane rather than `executive-action` for two reasons: GAO is a
# LEGISLATIVE-branch auditor, so filing it as an executive action mislabels it;
# and at ~24 reports per 21 days it outweighs everything else on the tab, so it
# needs to be collapsible the same way it was on the Congress tab.
#
# gao.gov/rss/press.xml is NOT included — it has published nothing since
# 2026-06-04, and its releases are announcements of the same reports.
# ---------------------------------------------------------------------------
OVERSIGHT_SOURCES = [
    {
        "name": "GAO reports", "outlet": "GAO", "agency": "gao", "kind": "rss",
        "url": "https://www.gao.gov/rss/reports.xml",
        # The feed holds exactly 25 items — about three weeks at GAO's cadence —
        # so the daily run is what keeps this whole. A backfill longer than
        # three weeks cannot reach back through it.
    },
]

# ---------------------------------------------------------------------------
# LANE: rulemaking. Federal Register API.
#
# The whole Register is 1,637 documents per 21 days, ~99% of it ordinary
# agency regulatory business (FDA color-additive petitions and the like) plus
# ~525 routine Paperwork Reduction Act collection renewals. Pulling all of it
# would cost 10x for a handful more events, so this is scoped three ways:
#
#   1. agencies  — everything from the agencies whose subject matter IS the
#                  machinery of government. Full coverage, no keyword risk.
#   2. types     — every presidential document. EOs and presidential memos on
#                  the workforce, procurement or agency structure are top-tier
#                  capacity signal and there are only ~17 per 21 days.
#   3. terms     — a capacity-vocabulary sweep across ALL agencies, to catch
#                  the mission-agency actions (VA benefits systems, DoD
#                  acquisition) that scoping by agency would miss.
#
# Slugs verified against the API on 2026-08-19; counts are for 2026-07-29..08-19.
# `information-and-regulatory-affairs-office` and
# `federal-acquisition-regulation-council` are NOT valid slugs — OIRA files
# under management-and-budget-office and the FAR Council under the three
# procuring agencies (DoD/GSA/NASA).
# ---------------------------------------------------------------------------
FEDREG_AGENCIES = [
    ("personnel-management-office", "opm"),                    # 12
    ("management-and-budget-office", "omb"),                   # 7
    ("general-services-administration", "gsa"),                # 10
    ("merit-systems-protection-board", "mspb"),                # 1
    ("federal-labor-relations-authority", "flra"),             # 0 — valid, quiet
    ("government-ethics-office", "oge"),                       # 0 — valid, quiet
    ("national-archives-and-records-administration", "nara"),  # 5
]

# Every EO and presidential memorandum. `PRESDOCU` also carries proclamations,
# which are ceremonial — the gate drops them.
FEDREG_TYPES = ["PRESDOCU"]

# Full-text phrases, quoted so the API matches the phrase and not the words.
# Counts per 21 days in comments; total ~160 with overlap, deduped on
# document_number before the gate sees them.
FEDREG_TERMS = [
    '"federal workforce"',              # 5
    '"civil service"',                  # 13
    '"Schedule F"',                     # 4
    '"reduction in force"',             # 5
    '"hiring authority"',               # 1
    '"human capital"',                  # 9
    '"Federal Acquisition Regulation"',  # 16
    '"Technology Modernization Fund"',  # 0 — kept; it moves in bursts
    '"FedRAMP"',                        # 5
    '"Login.gov"',                      # 2
    '"shared services"',                # 6
    '"artificial intelligence"',        # 27 — noisiest; much of it regulates
                                        #      private AI, which the gate drops
    '"data governance"',                # 20
    '"improper payments"',              # 9
    '"burden reduction"',               # 16
    '"regulatory reform"',              # 5
    '"customer experience"',            # 2
    '"government efficiency"',          # 15
]


def fedreg_specs():
    """One spec per query, so the dry-run funnel reports yield per query and a
    query that silently stops matching is visible instead of invisible."""
    out = []
    for slug, agency in FEDREG_AGENCIES:
        out.append({
            "name": f"FR agency — {agency.upper()}", "agency": agency,
            "kind": "fedreg-api", "query": {"conditions[agencies][]": slug},
        })
    for t in FEDREG_TYPES:
        out.append({
            "name": f"FR type — {t}", "agency": "white-house",
            "kind": "fedreg-api", "query": {"conditions[type][]": t},
        })
    for term in FEDREG_TERMS:
        out.append({
            "name": f"FR term — {term.strip(chr(34))}", "agency": "",
            "kind": "fedreg-api", "query": {"conditions[term]": term},
        })
    return out


LANE_OF = {"news": NEWS_SOURCES, "executive-action": AGENCY_SOURCES,
           "oversight": OVERSIGHT_SOURCES}


def all_federal_sources():
    """Yield (lane, spec) for every source. `spec` always carries name, kind,
    and (for agency and Federal Register sources) a default `agency`."""
    for lane, specs in LANE_OF.items():
        for s in specs:
            yield lane, s
    for s in fedreg_specs():
        yield "rulemaking", s


def source_count():
    return sum(1 for _ in all_federal_sources())


def as_json():
    """Registry snapshot for the web methodology view."""
    return {
        "lanes": {
            "executive-action": "Agency primary sources — what the executive branch did, in its own words",
            "oversight": "GAO — the audit record of whether federal programs and systems work",
            "news": "Federal trade press and The Hill — second-hand, but catches what agencies don't announce",
            "rulemaking": "Federal Register — the legal record of rules, notices and presidential documents",
        },
        "sources": [
            {"lane": lane, "kind": s["kind"], "name": s["name"],
             "outlet": s.get("outlet", ""), "agency": s.get("agency", ""),
             "broad": bool(s.get("broad")),
             "url": s.get("url") or (f"{s['base']}/{s['post_type']}" if s.get("base")
                                     else "https://www.federalregister.gov/api/v1/documents.json")}
            for lane, s in all_federal_sources()
        ],
        "fedreg": {"agencies": FEDREG_AGENCIES, "types": FEDREG_TYPES, "terms": FEDREG_TERMS},
    }


if __name__ == "__main__":
    if "--json" in sys.argv:
        print(json.dumps(as_json(), indent=2))
    else:
        by_lane = {}
        for lane, spec in all_federal_sources():
            by_lane.setdefault(lane, []).append(spec)
        for lane, specs in by_lane.items():
            print(f"\n{lane}  ({len(specs)})")
            for s in specs:
                flag = " [broad]" if s.get("broad") else ""
                print(f"  {s['kind']:11} {s.get('agency') or '-':14} {s['name']}{flag}")
        print(f"\ntotal: {source_count()} sources "
              f"({len(NEWS_SOURCES)} news, {len(AGENCY_SOURCES)} agency, "
              f"{len(OVERSIGHT_SOURCES)} oversight, "
              f"{len(fedreg_specs())} Federal Register queries)")
