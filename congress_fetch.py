#!/usr/bin/env python3
"""Fetchers for the congressional press sources.

Every fetcher returns a list of item dicts with the same shape, so
congress_pipeline.py doesn't care where a row came from:

    {source, committee, party, kind, title, url, published (YYYY-MM-DD or ""),
     pub_date (date or None), body}

Failures return [] and print — one dead source must never kill a run. That's
the same contract as pipeline.parse_feed.
"""

import re
import time
import urllib.parse
from datetime import date, datetime

import feedparser
import requests
from bs4 import BeautifulSoup

UA = "Recoding America State Capacity Tracker (+atharv@recodingamerica.fund)"
HEADERS = {"User-Agent": UA}
TIMEOUT = 30
DELAY = 1.0          # between requests to the same host
BODY_CHARS = 4000    # HSGAC bodies run 3-4KB; RSS blurbs are far shorter

_MONTHS = ("january february march april may june july august september "
           "october november december").split()


def strip_html(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


# ---------------------------------------------------------------------------
# Dates. Four formats across these sites: ISO from a <time datetime>,
# "August 3, 2026", "08.12.2026" (mm.dd.yyyy), and "7/2/26" (m/d/yy).
# ---------------------------------------------------------------------------
def parse_date_text(text):
    if not text:
        return None
    t = text.strip()

    m = re.search(r"(20\d\d)-(\d{2})-(\d{2})", t)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(20\d\d)", t)
    if m:
        mon = m.group(1).lower()
        idx = next((i for i, name in enumerate(_MONTHS) if name.startswith(mon[:3])), None)
        if idx is not None:
            try:
                return date(int(m.group(3)), idx + 1, int(m.group(2)))
            except ValueError:
                return None

    # mm.dd.yyyy — must come before m/d/yy so "08.12.2026" isn't misread.
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(20\d\d)\b", t)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None

    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", t)
    if m:
        y = int(m.group(3))
        y += 2000 if y < 100 else 0
        try:
            return date(y, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


def polite_get(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            print(f"  HTTP {r.status_code} {url}")
            return None
        return r.text
    except Exception as e:
        print(f"  fetch error {url}: {e}")
        return None


def _item(spec, kind, title, url, pub, body):
    return {
        "source": spec["name"], "committee": spec["committee"],
        "party": spec["party"], "kind": kind,
        "title": strip_html(title)[:500],
        "url": url or "",
        "published": pub.isoformat() if pub else "",
        "pub_date": pub,
        "body": strip_html(body)[:BODY_CHARS],
    }


# ---------------------------------------------------------------------------
# wp_api — HSGAC
# ---------------------------------------------------------------------------
def fetch_wp_api(spec, min_date, max_pages=10):
    """WordPress REST with ?after= server-side date filtering, so we pull only
    the window instead of paging back through thousands of posts."""
    out, page = [], 1
    after = f"{min_date.isoformat()}T00:00:00"
    while page <= max_pages:
        url = (f"{spec['base']}/{spec['post_type']}"
               f"?after={after}&per_page=100&page={page}&orderby=date&order=desc")
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        except Exception as e:
            print(f"  fetch error {url}: {e}")
            break
        if r.status_code == 400:
            break          # past the last page — WP returns 400, not an empty list
        if r.status_code != 200:
            print(f"  HTTP {r.status_code} {url}")
            break
        try:
            posts = r.json()
        except ValueError:
            break
        if not posts:
            break
        for p in posts:
            pub = parse_date_text((p.get("date") or "")[:10])
            out.append(_item(
                spec, "wp_api",
                p.get("title", {}).get("rendered", ""),
                p.get("link", ""),
                pub,
                p.get("content", {}).get("rendered", ""),
            ))
        if len(posts) < 100:
            break
        page += 1
        time.sleep(DELAY)
    return out


# ---------------------------------------------------------------------------
# rss
# ---------------------------------------------------------------------------
def _entry_date(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return date(t.tm_year, t.tm_mon, t.tm_mday)
    return parse_date_text(entry.get("published") or entry.get("updated") or "")


def fetch_rss(spec, min_date):
    try:
        entries = feedparser.parse(spec["url"]).entries
    except Exception as e:
        print(f"  fetch error {spec['url']}: {e}")
        return []
    out = []
    for e in entries:
        pub = _entry_date(e)
        if pub and pub < min_date:
            continue
        body = e.get("content", [{}])[0].get("value", "") if e.get("content") else ""
        out.append(_item(spec, "rss", e.get("title", ""), e.get("link", ""),
                         pub, body or e.get("summary", "")))
    return out


# ---------------------------------------------------------------------------
# html
# ---------------------------------------------------------------------------
def _abs(href, spec):
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return urllib.parse.urljoin(spec.get("base_url") or spec["url"], href)


def fetch_html(spec, min_date):
    html = polite_get(spec["url"])
    if html is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out = []

    for el in soup.select(spec["item"]):
        # --- table layouts (Comer, McConnell): date in one cell, link in another
        if "td_title" in spec:
            tds = el.find_all("td")
            if len(tds) <= max(spec["td_date"], spec["td_title"]):
                continue          # header row
            pub = parse_date_text(tds[spec["td_date"]].get_text(" ", strip=True))
            a = tds[spec["td_title"]].find("a", href=True)
            if not a:
                continue
            title, href = a.get_text(" ", strip=True), a["href"]
        else:
            a = el.find("a", href=True)
            if not a:
                continue
            href = a["href"]
            title = a.get_text(" ", strip=True)
            pub = None
            if "date_attr" in spec:
                tag, attr = spec["date_attr"]
                node = el.find(tag)
                if node is not None:
                    pub = parse_date_text(node.get(attr) or node.get_text(strip=True))
            item_text = el.get_text(" ", strip=True)
            if pub is None:
                pub = parse_date_text(item_text)
            # House Administration wraps the whole row in an image link, so the
            # anchor has no text — fall back to the row text with the leading
            # date and kicker label stripped off.
            if len(title) < 12:
                title = re.sub(r"^\s*(?:Press Release|News|Statement)\s*", "", re.sub(
                    r"^\s*(?:\d{1,2}[./]\d{1,2}[./]\d{2,4}"
                    r"|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+20\d\d)\s*", "", item_text)).strip()
            # On other templates the date leads the anchor text instead.
            title = re.sub(
                r"^\s*(?:\d{1,2}[./]\d{1,2}[./]\d{2,4}|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+20\d\d)\s*",
                "", title).strip()

        if not title or len(title) < 12:
            continue
        # An undated row on these listing templates is chrome (nav, sidebar,
        # office-hours block), not a release. Requiring a date is what keeps
        # the broad `div.views-row` selectors honest.
        if pub is None or pub < min_date:
            continue
        # Listing pages carry no body; the classifier works off the title.
        # Full text would need a second request per item — not worth it when
        # congressional headlines are already declarative.
        out.append(_item(spec, "html", title, _abs(href, spec), pub, ""))

    # Listings repeat links (featured block + main list). Keep first occurrence.
    seen, deduped = set(), []
    for it in out:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        deduped.append(it)
    return deduped


FETCHERS = {"wp_api": fetch_wp_api, "rss": fetch_rss, "html": fetch_html}


def fetch_source(kind, spec, min_date):
    try:
        return FETCHERS[kind](spec, min_date)
    except Exception as e:
        print(f"  FETCHER CRASH {spec['name']}: {e}")
        return []


if __name__ == "__main__":
    # Reachability probe: every source should report a non-zero fetch.
    # A zero means a moved feed or a changed selector, not a quiet committee.
    import argparse
    from datetime import timedelta
    import congress_sources

    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=21)
    args = ap.parse_args()
    min_date = date.today() - timedelta(days=args.days)

    print(f"Probing all sources, window >= {min_date}\n")
    total, dead = 0, []
    for kind, spec in congress_sources.all_congress_sources():
        items = fetch_source(kind, spec, min_date)
        total += len(items)
        newest = max((i["published"] for i in items if i["published"]), default="—")
        print(f"  {len(items):4}  {newest:>10}  {kind:6}  {spec['name']}")
        if not items:
            dead.append(spec["name"])
    print(f"\n{total} items from {congress_sources.source_count()} sources")
    if dead:
        print(f"ZERO items ({len(dead)}): {', '.join(dead)}")
