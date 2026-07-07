#!/usr/bin/env python3
"""Gov Candidates — static platform scrape.

For each candidate in 'Gov Candidates' with a campaign website: fetch the site,
discover issue/platform pages (one hop; links whose text or path matches
issues/priorities/plan/policy/agenda/vision), extract the text, and run one
Claude call with RAF's four-competency lens to produce:

  platform_summary    - what the candidate's EXISTING platform says on RAF's
                        competencies (e.g. Weiser's reg-reform record + EO plan)
  competency_signals  - which of the four competencies the platform touches
  platform_sources    - the URLs actually read
  platform_asof       - today

Writes back to the 'Gov Candidates' row. Candidates whose platform_asof is
already set are skipped unless --force.

Usage:
    python candidate_platforms.py                  # all unscraped candidates
    python candidate_platforms.py --state CO       # one state
    python candidate_platforms.py --candidate "Phil Weiser"
    python candidate_platforms.py --force          # re-scrape
    python candidate_platforms.py --dry-run        # print, don't write
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
from datetime import date

import requests
from anthropic import Anthropic
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pyairtable import Api

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")
if not (ANTHROPIC_API_KEY and AIRTABLE_TOKEN and AIRTABLE_BASE_ID):
    sys.exit("Missing env vars — need ANTHROPIC_API_KEY, AIRTABLE_TOKEN, AIRTABLE_BASE_ID.")

CANDIDATES_TABLE = "Gov Candidates"
MODEL = "claude-sonnet-4-6"
COMPETENCY_CHOICES = ["civil-service", "procedure", "digital", "incentives"]

UA = {"User-Agent": "Mozilla/5.0 (compatible; RAF-StateTracker/1.0)"}
ISSUE_RE = re.compile(
    r"issue|priorit|plan|policy|policies|platform|agenda|vision|record", re.I)
MAX_PAGES = 8
MAX_CHARS_PER_PAGE = 12000
MAX_TOTAL_CHARS = 60000

SYSTEM_PROMPT = """You are profiling a 2026 gubernatorial candidate's EXISTING
public platform for RAF (Recoding America Fund). RAF works on four state-capacity
competencies — how a state government builds and runs ITSELF, not what it
regulates in the wider economy:

- civil-service: the state's own workforce system — hiring, classification,
  pay, performance, removal, where that authority sits.
- procedure: the state's procedural/compliance burden — regulatory reform,
  red-tape cutting, permitting, occupational licensing, government efficiency.
- digital: the state's own technology, data, and AI — IT modernization,
  digital service teams, how government builds/buys/oversees its tech.
- incentives: the learning loop — outcome-based funding, KPIs/dashboards,
  test-and-learn pilots, oversight that asks what's working.

You will get scraped text from the candidate's campaign site (and possibly
notes with sourced signals from prior research). Write:

1. "platform_summary" — 4-10 sentences, markdown-free plain text. Lead with the
   competency-relevant material: concrete plans, commitments (e.g. a pledged
   day-one executive order), and relevant record in current office. Then one or
   two sentences of overall platform context (their headline priorities, so the
   reader knows what the campaign is actually about). If the platform has
   NOTHING competency-relevant, say so plainly in the first sentence and give a
   2-3 sentence general platform sketch. Attribute claims to the pages they
   came from only when ambiguous — no URLs in the prose.
2. "competency_signals" — the competencies with a REAL signal (a stated plan,
   commitment, or record — not a stray keyword). Often empty; never stretch.
3. "confidence" — "high" if the site had substantive issue pages, "low" if you
   only saw thin or boilerplate text.

Statements and plans count the same as enacted actions. Direction-agnostic:
a plan to gut merit protections is a strong civil-service signal.

Output ONLY JSON:
{"platform_summary": "...", "competency_signals": [], "confidence": "high"}
"""


def fetch(url):
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"    fetch failed {url}: {e}")
        return ""


def page_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "form"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    return text[:MAX_CHARS_PER_PAGE]


def issue_links(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    host = urllib.parse.urlparse(base_url).netloc
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        href = urllib.parse.urljoin(base_url, a["href"].split("#")[0])
        p = urllib.parse.urlparse(href)
        if p.netloc != host or href in seen:
            continue
        label = a.get_text(" ").strip()
        if ISSUE_RE.search(label) or ISSUE_RE.search(p.path):
            seen.add(href)
            out.append(href)
    return out[:MAX_PAGES - 1]


def scrape_site(url):
    """Returns (pages_read, combined_text)."""
    home = fetch(url)
    if not home:
        return [], ""
    pages = [(url, page_text(home))]
    for link in issue_links(home, url):
        html = fetch(link)
        if html:
            pages.append((link, page_text(html)))
        if sum(len(t) for _, t in pages) > MAX_TOTAL_CHARS:
            break
    combined = "\n\n".join(f"=== {u} ===\n{t}" for u, t in pages if t)
    return [u for u, t in pages if t], combined[:MAX_TOTAL_CHARS]


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
    return json.loads(text)


def profile(client, rec_fields, site_text):
    user_msg = json.dumps({
        "candidate": rec_fields.get("candidate", ""),
        "state": rec_fields.get("state", ""),
        "party": rec_fields.get("party", ""),
        "current_role": rec_fields.get("current_role", ""),
        "status": rec_fields.get("status", ""),
        "prior_research_notes": rec_fields.get("notes", ""),
        "site_text": site_text,
    })
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=[{"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_msg}],
    )
    return parse_json_response(resp.content[0].text)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state", default="")
    ap.add_argument("--candidate", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    api = Api(AIRTABLE_TOKEN)
    table = api.base(AIRTABLE_BASE_ID).table(CANDIDATES_TABLE)
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    today = date.today().isoformat()

    todo = []
    for rec in table.all():
        f = rec["fields"]
        if (f.get("status") or "") in ("withdrawn", "defeated"):
            continue
        if args.state and (f.get("state") or "").upper() != args.state.upper():
            continue
        if args.candidate and args.candidate.lower() not in (f.get("candidate") or "").lower():
            continue
        if f.get("platform_asof") and not args.force:
            continue
        if not f.get("website"):
            continue
        todo.append(rec)

    print(f"Scraping {len(todo)} candidate platforms...")
    done = failed = 0
    for rec in todo:
        f = rec["fields"]
        who = f"{f.get('state')} {f.get('candidate')}"
        print(f"\n{who} — {f['website']}")
        urls, text = scrape_site(f["website"])
        if not text:
            print("    no text extracted, skipping")
            failed += 1
            continue
        print(f"    read {len(urls)} pages, {len(text)} chars")
        try:
            result = profile(client, f, text)
        except Exception as e:
            print(f"    LLM error: {e}")
            failed += 1
            continue
        signals = [c for c in (result.get("competency_signals") or [])
                   if c in COMPETENCY_CHOICES]
        summary = (result.get("platform_summary") or "").strip()
        print(f"    signals: {', '.join(signals) or '(none)'} "
              f"[confidence: {result.get('confidence', '?')}]")
        print(f"    {summary[:200]}")
        if args.dry_run:
            done += 1
            continue
        table.update(rec["id"], {
            "platform_summary": summary,
            "competency_signals": signals,
            "platform_sources": "\n".join(urls),
            "platform_asof": today,
        }, typecast=True)
        done += 1

    print(f"\nDone: {done} profiled, {failed} failed, "
          f"{len(todo) - done - failed} skipped.")


if __name__ == "__main__":
    main()
