"""Source registry for the Ecosystem Writing Tracker.

Curated Recoding America think-tank and nonprofit partner outlets — Substacks, org blogs,
and standard-CMS publications. All treated as trusted "skim" sources: no
relevance gate, the pipeline enriches everything that passes the content check.

Feed URLs RSS-verified on 2026-06-16 via the Task 0 sweep (ecosystem-tracker-spec
§4). For each candidate the sweep tried the given URL, then fell back through
common patterns (/feed, /feed/, /rss/, /rss.xml, ?format=rss) and HTML
<link rel="alternate"> autodiscovery. The URL recorded below is the one that
resolved to a valid feed with recent entries. This is a living list — re-run the
sweep and prune dead feeds as outlets change CMS.

Held / deferred (NOT in the skim set) — see ECOSYSTEM_HELD and ECOSYSTEM_NO_FEED
below for the record of orgs the sweep could not include in v1.
"""

# org -> verified feed URL. The skim set the pipeline actually fetches.
ECOSYSTEM_SOURCES = [
    # --- Substack-pattern outlets ---
    {"org": "Artificial Weights", "feed_url": "https://artificialweights.substack.com/feed"},
    {"org": "Art of Association", "feed_url": "https://artofassociation.substack.com/feed"},
    {"org": "IFP (Substack)", "feed_url": "https://instituteforprogress.substack.com/feed"},
    {"org": "Launchpad", "feed_url": "https://horizonlaunchpad.substack.com/feed"},
    {"org": "Slow Boring", "feed_url": "https://www.slowboring.com/feed"},
    {"org": "Statecraft", "feed_url": "https://www.statecraft.pub/feed"},
    {"org": "The Argument", "feed_url": "https://www.theargumentmag.com/feed"},
    {"org": "Eating Policy", "feed_url": "https://www.eatingpolicy.com/feed"},
    {"org": "Hypertext", "feed_url": "https://hypertextmag.com/feed"},
    # --- Standard-CMS publications & org blogs ---
    {"org": "FedScoop", "feed_url": "https://fedscoop.com/feed/"},
    {"org": "American Affairs", "feed_url": "https://americanaffairsjournal.org/feed/"},
    {"org": "Factory Settings", "feed_url": "https://www.factorysettings.org/feed/"},
    {"org": "Commonplace", "feed_url": "https://www.commonplace.org/feed/"},
    {"org": "American Compass", "feed_url": "https://americancompass.org/feed/"},
    {"org": "POPVOX", "feed_url": "https://www.popvox.org/blog/rss.xml"},
    {"org": "Roosevelt Institute", "feed_url": "https://rooseveltinstitute.org/publications/feed"},
    {"org": "Institute for Progress", "feed_url": "https://ifp.org/feed"},
    {"org": "American Governance Institute", "feed_url": "https://americalabs.org/feed"},
    {"org": "Credential Engine", "feed_url": "https://credentialengine.org/feed"},
    {"org": "Burnes Center", "feed_url": "https://burnes.northeastern.edu/feed"},
    {"org": "Democracy Forward", "feed_url": "https://democracyforward.org/feed"},
    {"org": "IBM Center for the Business of Government", "feed_url": "https://www.businessofgovernment.org/rss.xml"},
    {"org": "Stanford RegLab", "feed_url": "https://reglab.stanford.edu/publications/feed"},
    {"org": "Congressional Management Foundation", "feed_url": "https://www.congressfoundation.org/news/rss.xml"},
    {"org": "City Journal", "feed_url": "https://www.city-journal.org/rss.xml"},
    {"org": "Partnership for Public Service", "feed_url": "https://ourpublicservice.org/feed"},
    {"org": "Partners in Public Innovation", "feed_url": "https://www.publicinnovation.net/blog-feed.xml"},
]

# Broad-ish orgs (ecosystem-tracker-spec §4 / §9). A working feed exists, but
# only WHOLE-SITE — no narrow section feed — so pure skim would inject
# off-topic items. Per §9 recommendation (a), held for v1. Promote in phase 2
# behind a light topical filter.
ECOSYSTEM_HELD = [
    {"org": "Manhattan Institute", "feed_url": "https://manhattan.institute/rss.xml",
     "reason": "whole-site feed only; mixed topics (education, SSI, crime)"},
    {"org": "Niskanen Center", "feed_url": "https://www.niskanencenter.org/feed",
     "reason": "state-capacity section feed 404s; whole-site feed is mixed-topic"},
]

# Orgs the sweep found NO usable feed for. Defer to a phase-2 HTML-scrape
# decision (ecosystem-tracker-spec §9). Notes record what the sweep observed.
ECOSYSTEM_NO_FEED = [
    {"org": "Cato", "note": "https://www.cato.org/rss/blog returns 403 (WAF blocks bots; would also fail in CI)"},
    {"org": "FAS Government Capacity", "note": "section feed 404s; root /feed/ is stale (newest entry 2023)"},
    {"org": "Reboot Democracy", "note": "no feed path resolves (rebootdemocracy.ai/feed 404)"},
    {"org": "USDR", "note": "Webflow site, no RSS"},
    {"org": "FAI", "note": "Next.js site, no RSS"},
    {"org": "Rainey Center", "note": "Webflow site, no RSS"},
    {"org": "Better Government Lab", "note": "no RSS"},
    {"org": "Data Foundation", "note": "no RSS (all feed paths 404 or HTML)"},
    {"org": "Inclusive Abundance", "note": "no RSS"},
    {"org": "SeedAI", "note": "Framer site, no RSS"},
    {"org": "NAPA Academy Insights", "note": "no RSS (napawash.org/feed 404)"},
    {"org": "New America", "note": "WordPress /feed/ exists but is empty (0 items); broad-ish anyway"},
    {"org": "R Street", "note": "WordPress /feed/ exists but is empty (0 items); broad-ish anyway"},
    {"org": "National Affairs", "note": "no RSS"},
]


def _domain(url):
    from urllib.parse import urlsplit
    return urlsplit(url).netloc


def all_feeds():
    """Yield (org, feed_url, source_domain) for every skim source."""
    for s in ECOSYSTEM_SOURCES:
        yield s["org"], s["feed_url"], _domain(s["feed_url"])


if __name__ == "__main__":
    import json
    import sys

    if "--json" in sys.argv:
        json.dump(
            {
                "verified": "2026-06-16",
                "sources": ECOSYSTEM_SOURCES,
                "held": ECOSYSTEM_HELD,
                "no_feed": ECOSYSTEM_NO_FEED,
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
    else:
        print(f"{sum(1 for _ in all_feeds())} skim feeds; "
              f"{len(ECOSYSTEM_HELD)} held; {len(ECOSYSTEM_NO_FEED)} no-feed. "
              f"Use --json for the registry.")
