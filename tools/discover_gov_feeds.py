#!/usr/bin/env python3
"""discover_gov_feeds.py — build a VERIFIED registry of all 50 governors' press sources.

One-shot reconnaissance for the gov-release work (see docs/specs/gov-releases-spec.md §5). It
does NOT hardcode or guess governor URLs. Instead it:

  1. SEEDS the 50 official governor-office sites from a canonical source. We read
     Wikipedia's "List of current United States governors" to get the authoritative
     list of states, then read each "Governor of <state>" office article and pull the
     "Website" link out of its infobox. That link is the official office site
     (e.g. Governor of New York -> https://www.governor.ny.gov/), not a guess.
  2. PROBES each site for a news/press index over the common paths.
  3. PROBES for RSS — both well-known feed paths and any <link rel="alternate"
     type="application/rss+xml"> advertised in the news page <head> — and VALIDATES
     every candidate with feedparser: it must parse AND return at least one dated entry.
  4. EMITS data/gov_sources.csv (state, governor_site, news_url, rss_url, status) and, for
     sites with no usable feed, a best-guess set of CSS selectors to seed
     sources.gov_html_sources().
  5. PRINTS paste-ready seed blocks for sources.py (RSS rows + the HTML-config registry)
     and a one-line "X of 50 have RSS, Y need HTML config." summary.

Nothing here writes to sources.py — review data/gov_sources.csv first, then wire it in.

Politeness: descriptive User-Agent, a small delay between fetches, and a per-site
try/except so one dead site never stops the sweep.

Usage:
    python discover_gov_feeds.py                # full 50-state sweep
    python discover_gov_feeds.py --states NY TX  # limit to specific states (USPS codes)
    python discover_gov_feeds.py --limit 5       # first N states only (smoke test)
"""

import argparse
import csv
import sys
import time
from collections import Counter
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (compatible; StateActivityTracker-GovFeedDiscovery/1.0; "
    "+https://github.com/ag1957/State-Tracker)"
)
HEADERS = {"User-Agent": UA}
TIMEOUT = 30
DELAY = 1.0  # seconds between network calls — be a good citizen

WIKI = "https://en.wikipedia.org"
GOV_LIST_PAGE = "/wiki/List_of_current_United_States_governors"

# USPS code <- state name. Reference data, not a guessed endpoint: it only maps the
# canonical state names we read off Wikipedia onto the two-letter codes sources.py uses.
STATE_ABBR = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
}

# Common newsroom landing paths, most-specific first.
NEWS_PATHS = [
    "/newsroom", "/news-releases", "/press-releases", "/news/press-releases",
    "/news", "/press", "/media", "/media/press-releases", "/newsroom/press-releases",
]

# Well-known feed paths to try against both the site root and the news index.
FEED_PATHS = [
    "/feed", "/rss", "/feed.xml", "/rss.xml", "/news/feed", "/news/rss",
    "/feed/", "/rss/", "/?format=rss",
]


def polite_get(url, allow_redirects=True):
    """GET with our UA and a small delay. Returns a Response or None on any failure."""
    time.sleep(DELAY)
    try:
        return requests.get(
            url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=allow_redirects
        )
    except requests.RequestException as e:
        print(f"    fetch error {url}: {e}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- seed

def _infobox_website(article_path):
    """Return the 'Website' href from a Wikipedia article's infobox, or None."""
    resp = polite_get(WIKI + article_path)
    if not resp or resp.status_code != 200:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    ib = soup.find("table", class_="infobox")
    if not ib:
        return None
    for tr in ib.find_all("tr"):
        hd = tr.find("th")
        if hd and "website" in hd.get_text(" ", strip=True).lower():
            a = tr.find("a", href=True)
            if a and a["href"].startswith("http"):
                return a["href"]
    return None


def seed_governor_sites(wanted=None):
    """Yield (abbr, state_name, governor_site) seeded from Wikipedia.

    Primary source per state is the 'Governor of <state>' OFFICE article infobox
    (the official office site). If that has no website row, fall back to the sitting
    governor's personal article infobox, whose link we read from the list table.
    """
    resp = polite_get(WIKI + GOV_LIST_PAGE)
    if not resp or resp.status_code != 200:
        sys.exit("Could not fetch the Wikipedia governors list — aborting.")
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", class_="wikitable")  # first wikitable = the 50 states

    rows = []
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        state = cells[0].get_text(" ", strip=True).split("(")[0].strip()
        if state not in STATE_ABBR:
            continue  # skip territories / stray rows
        # First non-list /wiki/ link after the state cell = the sitting governor's article.
        person = None
        for td in cells[1:]:
            for a in td.find_all("a", href=True):
                h = a["href"]
                if h.startswith("/wiki/") and ":" not in h and "list" not in h.lower():
                    person = h
                    break
            if person:
                break
        rows.append((STATE_ABBR[state], state, person))

    for abbr, state, person in rows:
        if wanted and abbr not in wanted:
            continue
        office_title = "/wiki/Governor_of_" + state.replace(" ", "_")
        site = _infobox_website(office_title)
        if not site and person:
            site = _infobox_website(person)  # fall back to the person's infobox
        yield abbr, state, site


# ----------------------------------------------------------------------- discovery

def base_of(url):
    """Scheme://host root for building probe URLs."""
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def looks_like_listing(html):
    """Cheap heuristic: a news index has many links and usually a date element."""
    soup = BeautifulSoup(html, "html.parser")
    links = soup.find_all("a", href=True)
    has_date = bool(soup.find("time")) or bool(soup.select("[class*=date],[class*=Date]"))
    return len(links) >= 15 and has_date


def find_news_index(site):
    """Probe common news paths; return (news_url, html) for the best hit, else (site, root_html)."""
    root = base_of(site)
    root_resp = polite_get(site)
    root_html = root_resp.text if root_resp and root_resp.ok else ""
    for path in NEWS_PATHS:
        resp = polite_get(urljoin(root + "/", path.lstrip("/")))
        if resp and resp.ok and "html" in resp.headers.get("Content-Type", "").lower():
            if looks_like_listing(resp.text):
                return resp.url, resp.text
    # No dedicated newsroom found — fall back to the homepage.
    return site, root_html


def head_alternate_feeds(html, page_url):
    """Pull advertised <link rel="alternate" type="application/rss+xml|atom+xml"> hrefs."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for link in soup.find_all("link", rel=True):
        rel = " ".join(link.get("rel", [])).lower()
        typ = (link.get("type") or "").lower()
        if "alternate" in rel and ("rss" in typ or "atom" in typ) and link.get("href"):
            out.append(urljoin(page_url, link["href"]))
    return out


def validate_feed(url):
    """True iff the URL parses as a feed AND has >=1 entry with a usable date.

    We fetch with our own UA (politeness + some sites 403 the default agent), then
    hand the bytes to feedparser so validation matches what the pipeline will see.
    """
    resp = polite_get(url)
    if not resp or not resp.ok:
        return False
    parsed = feedparser.parse(resp.content)
    if not parsed.entries:
        return False
    return any(
        e.get("published_parsed") or e.get("updated_parsed") for e in parsed.entries
    )


def probe_rss(site, news_url, news_html):
    """Return the first validated feed URL, else None.

    Candidates, in priority order: feeds advertised in the news <head>, then
    well-known paths under both the news URL and the site root.
    """
    candidates = []
    candidates += head_alternate_feeds(news_html, news_url)
    roots = []
    for u in (news_url, site):
        b = base_of(u)
        if b not in roots:
            roots.append(b)
    for b in roots:
        for path in FEED_PATHS:
            candidates.append(urljoin(b + "/", path.lstrip("/")))

    seen = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        if validate_feed(c):
            return c
    return None


def guess_selectors(html):
    """Best-guess CSS selectors for a listing page — a STARTING config, not gospel.

    Find the date-bearing elements, climb to the smallest ancestor that also holds a
    link and real text (the repeating "card"), and take the dominant card signature.
    """
    soup = BeautifulSoup(html, "html.parser")

    times = soup.find_all("time")
    date_nodes = times or soup.select("[class*=date],[class*=Date]")
    if times:
        date_selector = "time"
    elif date_nodes and date_nodes[0].get("class"):
        date_selector = "." + ".".join(date_nodes[0]["class"])
    else:
        date_selector = None

    containers = Counter()
    example = {}
    for dn in date_nodes[:80]:
        node = dn
        for _ in range(5):
            node = node.parent
            if node is None or node.name in ("body", "html") or node.name is None:
                break
            if node.find("a", href=True) and len(node.get_text(strip=True)) > 20:
                cls = node.get("class") or []
                key = (node.name, " ".join(cls))
                containers[key] += 1
                example.setdefault(key, node)
                break

    if not containers:
        # Nothing date-shaped repeated — emit a generic guess to hand-correct.
        return {
            "item_selector": "article",
            "title_selector": "h2, h3",
            "link_selector": "a",
            "date_selector": date_selector or "time",
        }

    (tag, cls), _ = containers.most_common(1)[0]
    item_selector = tag + ("." + ".".join(cls.split()) if cls else "")
    card = example[(tag, cls)]
    heading = card.find(["h1", "h2", "h3", "h4"])
    if heading and heading.get("class"):
        title_selector = heading.name + "." + ".".join(heading["class"])
    elif heading:
        title_selector = heading.name
    else:
        title_selector = "a"
    return {
        "item_selector": item_selector,
        "title_selector": title_selector,
        "link_selector": "a",
        "date_selector": date_selector or "time",
    }


# ---------------------------------------------------------------------------- main

def sweep(states):
    """Run the full discovery for the seeded states; return a list of result rows."""
    results = []
    for abbr, state, site in seed_governor_sites(states):
        print(f"[{abbr}] {state}: {site or 'NO SITE FOUND'}")
        row = {
            "state": abbr,
            "governor_site": site or "",
            "news_url": "",
            "rss_url": "",
            "status": "needs-html-config",
            "selectors": {},
        }
        if not site:
            row["status"] = "no-site-found"
            results.append(row)
            continue
        try:
            news_url, news_html = find_news_index(site)
            row["news_url"] = news_url
            rss = probe_rss(site, news_url, news_html)
            if rss:
                row["rss_url"] = rss
                row["status"] = "rss-confirmed"
                print(f"    RSS confirmed: {rss}")
            else:
                row["selectors"] = guess_selectors(news_html)
                print(f"    no RSS — needs HTML config (news: {news_url})")
        except Exception as e:  # one bad site must never stop the sweep
            print(f"    ERROR probing {site}: {e}", file=sys.stderr)
            row["status"] = "error"
        results.append(row)
    return results


def write_csv(results, path="data/gov_sources.csv"):
    cols = ["state", "governor_site", "news_url", "rss_url", "status",
            "item_selector", "title_selector", "link_selector", "date_selector"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in results:
            sel = r.get("selectors") or {}
            w.writerow({
                "state": r["state"],
                "governor_site": r["governor_site"],
                "news_url": r["news_url"],
                "rss_url": r["rss_url"],
                "status": r["status"],
                "item_selector": sel.get("item_selector", ""),
                "title_selector": sel.get("title_selector", ""),
                "link_selector": sel.get("link_selector", ""),
                "date_selector": sel.get("date_selector", ""),
            })


def print_seed_blocks(results):
    """Paste-ready snippets for sources.py: RSS rows + the HTML-config registry."""
    rss = [r for r in results if r["status"] == "rss-confirmed"]
    html = [r for r in results if r["status"] == "needs-html-config"]

    print("\n" + "=" * 72)
    print("SEED BLOCK 1 — RSS governors (source_type='gov-release') for sources.py")
    print("=" * 72)
    print("GOV_RELEASE_FEEDS = {")
    for r in rss:
        print(f'    "{r["state"]}": {{"name": "Governor of {r["state"]} '
              f'(press releases)", "feed_url": "{r["rss_url"]}"}},')
    print("}")

    print("\n" + "=" * 72)
    print("SEED BLOCK 2 — HTML-config registry for sources.gov_html_sources()")
    print("=" * 72)
    print("def gov_html_sources():")
    print("    return [")
    for r in html:
        sel = r.get("selectors") or {}
        print("        {")
        print(f'            "state": "{r["state"]}",')
        print(f'            "name": "Governor of {r["state"]} (press releases)",')
        print(f'            "list_url": "{r["news_url"]}",')
        print(f'            "base_url": "{base_of(r["news_url"]) if r["news_url"] else ""}",')
        print(f'            "item_selector": "{sel.get("item_selector", "")}",')
        print(f'            "title_selector": "{sel.get("title_selector", "")}",')
        print(f'            "link_selector": "{sel.get("link_selector", "a")}",')
        print(f'            "date_selector": "{sel.get("date_selector", "")}",')
        print("        },")
    print("    ]")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--states", nargs="*", help="USPS codes to limit the sweep, e.g. NY TX")
    ap.add_argument("--limit", type=int, help="only the first N seeded states (smoke test)")
    ap.add_argument("--csv", default="data/gov_sources.csv", help="output CSV path")
    args = ap.parse_args()

    wanted = {s.upper() for s in args.states} if args.states else None
    results = sweep(wanted)
    if args.limit:
        results = results[: args.limit]

    write_csv(results, args.csv)
    print_seed_blocks(results)

    total = len(results)
    rss = sum(1 for r in results if r["status"] == "rss-confirmed")
    html = sum(1 for r in results if r["status"] == "needs-html-config")
    print(f"\nWrote {args.csv} ({total} states).")
    print(f"{rss} of {total} have RSS, {html} need HTML config.")
    other = total - rss - html
    if other:
        print(f"({other} had no site or errored — see the CSV.)")


if __name__ == "__main__":
    main()
