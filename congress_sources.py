#!/usr/bin/env python3
"""Congressional source registry.

Mirrors sources.py: hardcoded dicts, one generator that flattens them. Adding a
source is an edit here plus a commit — same contract as the state feeds.

Three source kinds, all press/activity only:
  wp_api  — HSGAC's WordPress REST API (typed endpoints, full article bodies)
  rss     — a working RSS feed
  html    — a server-rendered listing page + selector config

Hearings and bills do NOT live here. Congress.gov covers both chambers with
canonical structured data; see congress_api.py / congress_api_sync.py. The one
exception is HSGAC's own `hearings` endpoint, kept below as a freshness
cross-check against the API (see CROSSCHECK_WP_HEARINGS).

Every URL here was probed live on 2026-08-13 and returned items.

    python congress_sources.py          # print the registry
    python congress_sources.py --json   # machine-readable, for the web view
"""

import json
import sys

# ---------------------------------------------------------------------------
# The seven committees. `code` is the Congress.gov systemCode — the join key
# between the scraped press path and the API path.
# ---------------------------------------------------------------------------
COMMITTEES = {
    "hsgac": {
        "code": "ssga00", "chamber": "senate",
        "name": "Senate Homeland Security & Governmental Affairs",
        "chair": "Rand Paul (R-KY)", "ranking": "Gary Peters (D-MI)",
    },
    "senate-rules": {
        "code": "ssra00", "chamber": "senate",
        "name": "Senate Rules & Administration",
        "chair": "Mitch McConnell (R-KY)", "ranking": "Alex Padilla (D-CA)",
    },
    "senate-approps": {
        "code": "ssap00", "chamber": "senate",
        "name": "Senate Appropriations",
        "chair": "Susan Collins (R-ME)", "ranking": "Patty Murray (D-WA)",
    },
    "house-oversight": {
        "code": "hsgo00", "chamber": "house",
        "name": "House Oversight & Government Reform",
        "chair": "James Comer (R-KY)", "ranking": "Robert Garcia (D-CA)",
    },
    "house-admin": {
        "code": "hsha00", "chamber": "house",
        "name": "House Administration",
        "chair": "Bryan Steil (R-WI)", "ranking": "Joseph Morelle (D-NY)",
    },
    "house-rules": {
        "code": "hsru00", "chamber": "house",
        "name": "House Rules",
        "chair": "Virginia Foxx (R-NC)", "ranking": "James McGovern (D-MA)",
    },
    "house-approps": {
        "code": "hsap00", "chamber": "house",
        "name": "House Appropriations",
        "chair": "Tom Cole (R-OK)", "ranking": "Rosa DeLauro (D-CT)",
    },
}

# systemCode -> our key, for filtering API responses.
CODE_TO_COMMITTEE = {v["code"]: k for k, v in COMMITTEES.items()}

# Non-committee sources that still map to a `committee` column in Airtable.
EXTRA_COMMITTEES = {
    "leadership": {"chamber": "house", "name": "Chamber leadership (whips)"},
    "gao": {"chamber": "n/a", "name": "Government Accountability Office"},
    "cbo": {"chamber": "n/a", "name": "Congressional Budget Office"},
}

# ---------------------------------------------------------------------------
# wp_api — HSGAC. Open, unauthenticated, supports ?after=<ISO>&per_page=100.
# Returns full content.rendered, so the classifier sees the whole release
# rather than an RSS blurb.
# ---------------------------------------------------------------------------
WP_API_SOURCES = [
    {
        "name": "HSGAC majority", "committee": "hsgac", "party": "majority",
        "base": "https://www.hsgac.senate.gov/wp-json/wp/v2", "post_type": "rep_press_releases",
    },
    {
        "name": "HSGAC minority", "committee": "hsgac", "party": "minority",
        "base": "https://www.hsgac.senate.gov/wp-json/wp/v2", "post_type": "dem_press_releases",
    },
    # padilla.senate.gov is also WordPress. Its /feed/ is a partial that stops
    # in Sept 2025; the API has the full press_releases post type.
    {
        "name": "Alex Padilla (Sen Rules ranking)", "committee": "senate-rules", "party": "member",
        "base": "https://www.padilla.senate.gov/wp-json/wp/v2", "post_type": "press_releases",
    },
]

# Kept out of the press pipeline; congress_api_sync.py reads it to check
# whether the committee's own CMS posts hearing notices ahead of Congress.gov.
CROSSCHECK_WP_HEARINGS = {
    "committee": "hsgac",
    "base": "https://www.hsgac.senate.gov/wp-json/wp/v2",
    "post_type": "hearings",
}

# ---------------------------------------------------------------------------
# rss
# ---------------------------------------------------------------------------
RSS_SOURCES = [
    # --- committees ---
    {"name": "Senate Approps majority", "committee": "senate-approps", "party": "majority",
     "url": "https://www.appropriations.senate.gov/rss/feeds/?type=majority"},
    {"name": "Senate Approps minority", "committee": "senate-approps", "party": "minority",
     "url": "https://www.appropriations.senate.gov/rss/feeds/?type=minority"},
    {"name": "House Approps", "committee": "house-approps", "party": "majority",
     "url": "https://appropriations.house.gov/rss.xml"},
    {"name": "House Rules minority", "committee": "house-rules", "party": "minority",
     "url": "https://democrats-rules.house.gov/rss.xml"},

    # --- chairs and ranking members ---
    {"name": "Rand Paul (HSGAC chair)", "committee": "hsgac", "party": "member",
     "url": "https://www.paul.senate.gov/feed/"},
    {"name": "Patty Murray (Sen Approps ranking)", "committee": "senate-approps", "party": "member",
     "url": "https://www.murray.senate.gov/feed/"},
    # Garcia / Steil / Morelle publish an rss.xml, but it carries district
    # service pages ("Bellflower", "FY2024 Community Project Funding") and
    # stops in 2023 — not press releases. Their listing pages are current, so
    # they're scraped below instead.
    {"name": "Tom Cole (House Approps chair)", "committee": "house-approps", "party": "member",
     "url": "https://cole.house.gov/rss.xml"},
    {"name": "Rosa DeLauro (House Approps ranking)", "committee": "house-approps", "party": "member",
     "url": "https://delauro.house.gov/rss.xml"},
    # Foxx and Emmer post infrequently — months between items is their cadence,
    # not a broken feed. Don't "fix" a zero here without checking the site.
    {"name": "Virginia Foxx (House Rules chair)", "committee": "house-rules", "party": "member",
     "url": "https://foxx.house.gov/news/rss.aspx"},
    {"name": "James McGovern (House Rules ranking)", "committee": "house-rules", "party": "member",
     "url": "https://mcgovern.house.gov/news/rss.aspx"},

    # --- whips ---
    {"name": "Majority Whip (Emmer)", "committee": "leadership", "party": "majority",
     "url": "https://www.majoritywhip.gov/news/rss.aspx"},
    {"name": "Minority Whip (Clark)", "committee": "leadership", "party": "minority",
     "url": "https://democraticwhip.house.gov/rss.xml"},

    # --- nonpartisan support agencies ---
    {"name": "GAO reports", "committee": "gao", "party": "nonpartisan",
     "url": "https://www.gao.gov/rss/reports.xml"},
    {"name": "CBO publications", "committee": "cbo", "party": "nonpartisan",
     "url": "https://www.cbo.gov/publications/all/rss.xml"},
]

# ---------------------------------------------------------------------------
# html — server-rendered listings. No JS anywhere; plain requests + BS4.
#
# `item` selects one row. `link`/`title`/`date` are selectors relative to it;
# omitted means "search the item". `date_attr` reads an attribute (a <time
# datetime>) in preference to text. `td_date`/`td_title` handle table layouts.
# Selectors verified against live HTML on 2026-08-13.
# ---------------------------------------------------------------------------
HTML_SOURCES = [
    {
        "name": "House Oversight releases", "committee": "house-oversight", "party": "majority",
        "url": "https://oversight.house.gov/release/",
        "item": "div.post", "date_attr": ("time", "datetime"),
    },
    {
        "name": "House Administration releases", "committee": "house-admin", "party": "majority",
        "url": "https://cha.house.gov/press-releases",
        "item": "div.media-digest", "base_url": "https://cha.house.gov",
    },
    {
        "name": "House Rules announcements", "committee": "house-rules", "party": "majority",
        "url": "https://rules.house.gov/media/announcements",
        "item": "div.views-row", "date_attr": ("time", "datetime"),
        "base_url": "https://rules.house.gov",
    },
    {
        "name": "House Rules releases", "committee": "house-rules", "party": "majority",
        "url": "https://rules.house.gov/media/press-releases",
        "item": "div.views-row", "date_attr": ("time", "datetime"),
        "base_url": "https://rules.house.gov",
    },
    {
        "name": "Senate Rules releases", "committee": "senate-rules", "party": "majority",
        "url": "https://www.rules.senate.gov/news/press-releases",
        "item": "div.ArticleBlock__titleContainer",
    },
    {
        "name": "Susan Collins (Sen Approps chair)", "committee": "senate-approps", "party": "member",
        "url": "https://www.collins.senate.gov/newsroom/press-releases",
        "item": "div.ArticleBlock__titleContainer",
    },
    {
        "name": "Gary Peters (HSGAC ranking)", "committee": "hsgac", "party": "member",
        "url": "https://www.peters.senate.gov/newsroom/press-releases",
        "item": "div.ArticleBlock",
    },
    {
        "name": "Robert Garcia (Oversight ranking)", "committee": "house-oversight", "party": "member",
        "url": "https://robertgarcia.house.gov/media/press-releases",
        "item": "div.views-row", "base_url": "https://robertgarcia.house.gov",
    },
    {
        "name": "Bryan Steil (House Admin chair)", "committee": "house-admin", "party": "member",
        "url": "https://steil.house.gov/media/press-releases",
        "item": "div.views-row", "base_url": "https://steil.house.gov",
    },
    {
        "name": "Joseph Morelle (House Admin ranking)", "committee": "house-admin", "party": "member",
        "url": "https://morelle.house.gov/media",
        "item": "div.evo-card", "base_url": "https://morelle.house.gov",
    },
    {
        "name": "James Comer (Oversight chair)", "committee": "house-oversight", "party": "member",
        "url": "https://comer.house.gov/press-release",
        "item": "tr", "td_date": 0, "td_title": 1,
        "base_url": "https://comer.house.gov",
    },
    {
        "name": "Mitch McConnell (Sen Rules chair)", "committee": "senate-rules", "party": "member",
        "url": "https://www.mcconnell.senate.gov/public/index.cfm/pressreleases",
        "item": "tr", "td_date": 0, "td_title": 1,
        "base_url": "https://www.mcconnell.senate.gov",
    },
]


def all_congress_sources():
    """Yield (kind, spec) for every press source. `spec` always carries
    name / committee / party."""
    for s in WP_API_SOURCES:
        yield "wp_api", s
    for s in RSS_SOURCES:
        yield "rss", s
    for s in HTML_SOURCES:
        yield "html", s


def source_count():
    return sum(1 for _ in all_congress_sources())


def as_json():
    """Registry snapshot for the web methodology view."""
    return {
        "committees": COMMITTEES,
        "extra": EXTRA_COMMITTEES,
        "sources": [
            {"kind": k, "name": s["name"], "committee": s["committee"],
             "party": s["party"], "url": s.get("url") or f"{s['base']}/{s['post_type']}"}
            for k, s in all_congress_sources()
        ],
    }


if __name__ == "__main__":
    if "--json" in sys.argv:
        print(json.dumps(as_json(), indent=2))
    else:
        by_kind = {}
        for kind, spec in all_congress_sources():
            by_kind.setdefault(kind, []).append(spec)
        for kind, specs in by_kind.items():
            print(f"\n{kind}  ({len(specs)})")
            for s in specs:
                print(f"  {s['committee']:16} {s['party']:12} {s['name']}")
        print(f"\ntotal: {source_count()} press sources, "
              f"{len(COMMITTEES)} committees on the API path")
