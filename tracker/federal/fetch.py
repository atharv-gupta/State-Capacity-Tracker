#!/usr/bin/env python3
"""Fetchers for the federal (executive-branch) sources.

Every fetcher returns a list of item dicts with the same shape, so
federal_pipeline.py doesn't care where a row came from:

    {source, outlet, lane, agency, kind, title, url, published,
     pub_date (date|None), body, document_url, instrument_hint,
     post_id, needs_hydrate}

Date parsing, HTML stripping and the polite GET are imported from
congress_fetch rather than re-implemented — the four date formats those
congressional sites use are the same four these federal sites use.

Two things here that the congressional fetchers don't need:

1. **Two-stage fetch for broad outlets.** The Hill publishes ~100 posts a day
   across every beat, and its WordPress API returns 3.6MB per 100 posts with
   bodies attached but 62KB without. So `lite_fields` sources are fetched
   title+excerpt only; federal_pipeline pre-screens on that and calls
   `hydrate_wp` for the survivors alone.

2. **Named parsers instead of selector configs.** OPM keeps its date in body
   text ("Date: August 10, 2026"), OMB news in a <time datetime>, OMB
   memoranda in a parenthetical on the link row, and GSA nowhere but the
   MMDDYYYY suffix of the URL slug. One selector schema covering all four would
   be harder to read than four small functions.

Failures return [] and print — one dead source must never kill a run.
"""

import re
import time
import urllib.parse
from datetime import date

import feedparser
import requests
from bs4 import BeautifulSoup

from tracker.congress.fetch import HEADERS, TIMEOUT, parse_date_text, polite_get, strip_html

DELAY = 1.0
BODY_CHARS = 4000
FEDREG_API = "https://www.federalregister.gov/api/v1/documents.json"


def _item(spec, lane, kind, title, url, pub, body, **extra):
    item = {
        "source": spec["name"],
        "outlet": spec.get("outlet") or spec["name"],
        "lane": lane,
        "agency": spec.get("agency") or "",
        "kind": kind,
        "title": strip_html(title)[:500],
        "url": url or "",
        "published": pub.isoformat() if pub else "",
        "pub_date": pub,
        "body": strip_html(body)[:BODY_CHARS],
        "document_url": "",
        "instrument_hint": "",
        "post_id": None,
        "needs_hydrate": False,
    }
    item.update(extra)
    return item


# ---------------------------------------------------------------------------
# wp_api — FedScoop, Federal News Network, MeriTalk, The Hill
# ---------------------------------------------------------------------------
LITE_FIELDS = "id,date,link,title,excerpt"
FULL_FIELDS = "id,date,link,title,excerpt,content"


def fetch_wp_api(spec, lane, min_date, max_pages=25):
    """WordPress REST with ?after= server-side filtering and X-WP-TotalPages
    paging. Returns items in publication order, newest first."""
    lite = bool(spec.get("lite_fields"))
    fields = LITE_FIELDS if lite else FULL_FIELDS
    out, page, total_pages = [], 1, 1
    while page <= min(max_pages, total_pages):
        url = (f"{spec['base']}/{spec['post_type']}"
               f"?after={min_date.isoformat()}T00:00:00&per_page=100&page={page}"
               f"&orderby=date&order=desc&_fields={fields}")
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        except Exception as e:
            print(f"  fetch error {spec['name']} p{page}: {e}")
            break
        if r.status_code == 400:
            break              # past the last page — WP returns 400, not []
        if r.status_code != 200:
            print(f"  HTTP {r.status_code} {spec['name']} p{page}")
            break
        try:
            posts = r.json()
        except ValueError:
            break
        if not posts:
            break
        try:
            total_pages = int(r.headers.get("X-WP-TotalPages") or 1)
        except ValueError:
            total_pages = 1
        for p in posts:
            body = (p.get("content", {}) or {}).get("rendered", "") if not lite else ""
            if not body:
                body = (p.get("excerpt", {}) or {}).get("rendered", "")
            out.append(_item(
                spec, lane, "wp_api",
                (p.get("title", {}) or {}).get("rendered", ""),
                p.get("link", ""),
                parse_date_text((p.get("date") or "")[:10]),
                body,
                post_id=p.get("id"),
                needs_hydrate=lite,
            ))
        page += 1
        if page <= total_pages:
            time.sleep(DELAY)
    return out


def hydrate_wp(items, batch=40):
    """Fill in full bodies for lite-fetched items, in place.

    Called by the pipeline AFTER the keyword pre-screen, so The Hill's ~2,000
    posts per backfill window cost one small request each per 40 survivors
    instead of 20 multi-megabyte pages.
    """
    by_base = {}
    for it in items:
        if it.get("needs_hydrate") and it.get("post_id"):
            by_base.setdefault(it["_base"], []).append(it)
    for base, group in by_base.items():
        for i in range(0, len(group), batch):
            chunk = group[i:i + batch]
            ids = ",".join(str(x["post_id"]) for x in chunk)
            url = f"{base}/posts?include={ids}&per_page={len(chunk)}&_fields=id,content"
            try:
                r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
                bodies = {p["id"]: (p.get("content", {}) or {}).get("rendered", "")
                          for p in r.json()} if r.status_code == 200 else {}
            except Exception as e:
                print(f"  hydrate error {base}: {e}")
                bodies = {}
            for x in chunk:
                got = bodies.get(x["post_id"])
                if got:
                    x["body"] = strip_html(got)[:BODY_CHARS]
                x["needs_hydrate"] = False
            time.sleep(0.3)
    return items


# ---------------------------------------------------------------------------
# rss — Nextgov, Government Executive
# ---------------------------------------------------------------------------
def _entry_date(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return date(t.tm_year, t.tm_mon, t.tm_mday)
    return parse_date_text(entry.get("published") or entry.get("updated") or "")


def fetch_rss(spec, lane, min_date):
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
        out.append(_item(spec, lane, "rss", e.get("title", ""), e.get("link", ""),
                         pub, body or e.get("summary", "")))
    return out


# ---------------------------------------------------------------------------
# html — one named parser per agency listing
# ---------------------------------------------------------------------------
def _abs(href, spec):
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return urllib.parse.urljoin(spec["url"], href)


def _parse_opm(soup, spec, lane, min_date):
    """OPM: USWDS collection list. The row text reads
    'TITLE Date: August 10, 2026 Contact: media@opm.gov'."""
    out = []
    for el in soup.select("li.usa-collection__item"):
        a = el.find("a", href=True)
        if not a:
            continue
        text = el.get_text(" ", strip=True)
        m = re.search(r"Date:\s*([A-Za-z]{3,9}\.?\s+\d{1,2},?\s+20\d\d)", text)
        pub = parse_date_text(m.group(1)) if m else parse_date_text(text)
        out.append(_item(spec, lane, "html", a.get_text(" ", strip=True),
                         _abs(a["href"], spec), pub, ""))
    return out


def _parse_omb_news(soup, spec, lane, min_date):
    """OMB newsroom: WordPress block list, date in a <time datetime>."""
    out = []
    for el in soup.select("li.wp-block-post"):
        a = el.find("a", href=True)
        if not a:
            continue
        t = el.find("time")
        pub = parse_date_text((t.get("datetime") if t else "") or el.get_text(" ", strip=True))
        out.append(_item(spec, lane, "html", a.get_text(" ", strip=True),
                         _abs(a["href"], spec), pub, ""))
    return out


_M_NUMBER = re.compile(r"\b(M-\d{2}-\d{2,3})\b", re.IGNORECASE)


def _parse_omb_memoranda(soup, spec, lane, min_date):
    """OMB memoranda: links straight to PDFs, with the date in a parenthetical
    on the link's row — 'M-26-17 Rescission of M-23-13 (August 10, 2026)'.

    The PDF body is not fetched (that would mean a PDF dependency for four
    documents a year); memo titles are declarative enough to gate on, and the
    memo number goes through as `instrument_hint` so the classifier never has
    to guess it.
    """
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not _M_NUMBER.search(href.split("/")[-1]):
            continue
        if href in seen:
            continue
        seen.add(href)
        row = a.find_parent(["li", "tr", "p", "div"])
        row_text = row.get_text(" ", strip=True) if row else a.get_text(" ", strip=True)
        m = re.search(r"\(([A-Za-z]{3,9}\.?\s+\d{1,2},?\s+20\d\d)\)", row_text)
        pub = parse_date_text(m.group(1)) if m else None
        num = _M_NUMBER.search(row_text) or _M_NUMBER.search(href)
        title = a.get_text(" ", strip=True) or row_text
        out.append(_item(spec, lane, "html", title, _abs(href, spec), pub,
                         row_text,
                         document_url=_abs(href, spec),
                         instrument_hint=num.group(1).upper() if num else ""))
    return out


_GSA_SLUG_DATE = re.compile(r"-(\d{2})(\d{2})(\d{4})/?$")


def _parse_gsa(soup, spec, lane, min_date):
    """GSA: table of releases whose only date is the MMDDYYYY suffix of the URL
    slug (…-rejects-misguided-bill-08182026)."""
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/newsroom/news-releases/" not in href:
            continue
        m = _GSA_SLUG_DATE.search(href)
        if not m:
            continue                     # the listing's own nav links
        url = _abs(href, spec)
        if url in seen:
            continue
        seen.add(url)
        try:
            pub = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            pub = None
        out.append(_item(spec, lane, "html", a.get_text(" ", strip=True), url, pub, ""))
    return out


HTML_PARSERS = {
    "opm": _parse_opm,
    "omb_news": _parse_omb_news,
    "omb_memoranda": _parse_omb_memoranda,
    "gsa": _parse_gsa,
}


def fetch_html(spec, lane, min_date):
    html = polite_get(spec["url"])
    if html is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    items = HTML_PARSERS[spec["parser"]](soup, spec, lane, min_date)
    # An undated row on these templates is chrome, not a release.
    return [i for i in items
            if i["title"] and len(i["title"]) >= 12
            and i["pub_date"] and i["pub_date"] >= min_date]


# Content containers on the four agency sites, most specific first. The listing
# pages carry no body text at all, and for the executive-action lane the body is
# what separates "issues governmentwide guidance" from "comments on".
_ARTICLE_SELECTORS = [
    "div.usa-prose", "div.field--name-body", "article .entry-content",
    "main article", "article", "main", "div#main-content",
]


def fetch_article_text(url):
    html = polite_get(url)
    if html is None:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    for sel in _ARTICLE_SELECTORS:
        node = soup.select_one(sel)
        if node and len(node.get_text(" ", strip=True)) > 200:
            return strip_html(node.get_text(" ", strip=True))[:BODY_CHARS]
    body = soup.find("body")
    return strip_html(body.get_text(" ", strip=True))[:BODY_CHARS] if body else ""


# ---------------------------------------------------------------------------
# fedreg-api — the Federal Register
# ---------------------------------------------------------------------------
FEDREG_FIELDS = [
    "document_number", "title", "abstract", "action", "type", "publication_date",
    "html_url", "pdf_url", "agency_names", "docket_ids", "topics", "citation",
    "executive_order_number", "significant",
]


def fetch_fedreg(spec, lane, min_date, max_pages=6):
    """One Federal Register query. `spec['query']` carries the scoping
    condition — an agency, a document type, or a quoted full-text phrase."""
    out, page = [], 1
    while page <= max_pages:
        params = {
            "per_page": 200, "page": page, "order": "newest",
            "conditions[publication_date][gte]": min_date.isoformat(),
        }
        params.update(spec["query"])
        # requests encodes a list value as repeated params, which is what the
        # fields[] and conditions[...][] array syntax needs.
        params["fields[]"] = FEDREG_FIELDS
        try:
            r = requests.get(FEDREG_API, params=params, headers=HEADERS, timeout=TIMEOUT)
        except Exception as e:
            print(f"  fetch error {spec['name']}: {e}")
            break
        if r.status_code != 200:
            print(f"  HTTP {r.status_code} {spec['name']}")
            break
        data = r.json()
        results = data.get("results") or []
        for d in results:
            pub = parse_date_text(d.get("publication_date") or "")
            eo = d.get("executive_order_number")
            body = " ".join(filter(None, [
                d.get("abstract") or "",
                f"Action: {d.get('action')}" if d.get("action") else "",
                f"Type: {d.get('type')}" if d.get("type") else "",
                f"Agencies: {', '.join(d.get('agency_names') or [])}",
                f"Topics: {', '.join(d.get('topics') or [])}" if d.get("topics") else "",
                f"Docket: {', '.join(d.get('docket_ids') or [])}" if d.get("docket_ids") else "",
            ]))
            out.append(_item(
                spec, lane, "fedreg-api", d.get("title", ""), d.get("html_url", ""),
                pub, body,
                document_url=d.get("html_url", ""),
                instrument_hint=(f"EO {eo}" if eo else (d.get("citation") or
                                                        d.get("document_number") or "")),
                fedreg_type=d.get("type") or "",
                fedreg_agencies=d.get("agency_names") or [],
            ))
        if len(results) < 200 or not data.get("next_page_url"):
            break
        page += 1
        time.sleep(0.3)
    return out


FETCHERS = {"wp_api": fetch_wp_api, "rss": fetch_rss, "html": fetch_html,
            "fedreg-api": fetch_fedreg}


def fetch_source(lane, spec, min_date):
    try:
        items = FETCHERS[spec["kind"]](spec, lane, min_date)
    except Exception as e:
        print(f"  FETCHER CRASH {spec['name']}: {e}")
        return []
    # hydrate_wp needs the API base to batch by; carry it on the item rather
    # than re-deriving it from the URL.
    if spec.get("base"):
        for i in items:
            i["_base"] = spec["base"]
    return items


if __name__ == "__main__":
    # Reachability probe: every source should report a non-zero fetch, except
    # the Federal Register queries that are legitimately quiet for a window.
    import argparse
    from datetime import timedelta

    from tracker.federal import sources as federal_sources

    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("--lane", help="news | executive-action | rulemaking")
    args = ap.parse_args()
    min_date = date.today() - timedelta(days=args.days)

    print(f"Probing federal sources, window >= {min_date}\n")
    total, dead = 0, []
    for lane, spec in federal_sources.all_federal_sources():
        if args.lane and lane != args.lane:
            continue
        items = fetch_source(lane, spec, min_date)
        total += len(items)
        newest = max((i["published"] for i in items if i["published"]), default="—")
        print(f"  {len(items):5}  {newest:>10}  {lane:16} {spec['name']}")
        if not items:
            dead.append(spec["name"])
    print(f"\n{total} items fetched")
    if dead:
        print(f"ZERO items ({len(dead)}): {', '.join(dead)}")
