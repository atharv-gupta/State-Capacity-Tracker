#!/usr/bin/env python3
"""Government Capacity Tracker — weekly email digest.

Runs after the dedupe steps each week and composes ONE email covering both
halves of the tracker:

    STATE      four competency sections (the original digest), then Governors '26
    FEDERAL    the week's calendar, then Congress by competency,
               then agencies and the executive branch by competency

Reads five clean tables — 'Events', 'Candidate Events', 'Congress Events',
'Congress Hearings', 'Federal Events' — selects the most notable items in each,
renders HTML + plain text, and sends via Resend.

Structure notes worth knowing before editing:

  * Every section renders through ONE item shape (see `item()`), so a new
    section is a loader plus a selection rule, not a new renderer. The previous
    version had a bespoke renderer per section and they had already drifted.
  * State shows all four competencies even when empty, because that rhythm is
    the tracker's spine and readers learn it. Federal OMITS empty competency
    subsections: it has two branch groups times four competencies, and eight
    "nothing notable" lines is a wall of nothing.
  * Congress comes before agencies inside FEDERAL, and the calendar comes before
    both, because upcoming hearings are the only perishable thing in the email.

Usage:
    python digest.py --days 7              # compose + send to RECIPIENTS
    python digest.py --days 7 --dry-run    # render + per-section counts, send nothing
    python digest.py --days 7 --html-out /tmp/d.html   # write the HTML to a file
    python digest.py --days 7 --to me@x.com            # override recipient
"""

import argparse
import os
import re
import sys
from datetime import date, datetime, timedelta
from html import escape

import requests
from dotenv import load_dotenv
from pyairtable import Api

load_dotenv()

AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
DIGEST_FROM = os.environ.get("DIGEST_FROM", "onboarding@resend.dev")

EVENTS_TABLE = "Events"
CANDIDATE_EVENTS_TABLE = "Candidate Events"
CANDIDATES_TABLE = "Gov Candidates"
CONGRESS_EVENTS_TABLE = "Congress Events"
CONGRESS_HEARINGS_TABLE = "Congress Hearings"
CONGRESS_BILLS_TABLE = "Congress Bills"
FEDERAL_EVENTS_TABLE = "Federal Events"

TRACKER_URL = os.environ.get("TRACKER_URL", "https://state-tracker-e2i7.vercel.app/")

# The digest covers both halves now, so the old "State Activity Digest from Last
# Week" subject undersold it. Kept fixed (no date or count) as before.
SUBJECT = "Capacity Digest: what states and Washington did last week"

INTRO = ("Everything you need to know about what state governments and the federal "
         "government got up to last week in the world of government capacity.")

RECIPIENTS = ["atharv@recodingamerica.org"]

COMPETENCIES = ["civil-service", "procedure", "digital", "incentives"]
COMPETENCY_LABELS = {
    "civil-service": "Civil service",
    "procedure": "Procedure",
    "digital": "Digital",
    "incentives": "Incentives",
}
# The web app's palette, so a competency reads the same colour in the email as
# it does on the tracker (web/app/lib/competencies.js).
COMPETENCY_COLORS = {
    "civil-service": "#059669",
    "procedure": "#d97706",
    "digital": "#2563eb",
    "incentives": "#7c3aed",
}

# An event spanning two competencies appears in EACH relevant section on the
# state side: state volume is high, overlap is uncommon, and repeating the
# occasional dual-competency event is cheaper than hiding it.
#
# On the federal side it appears ONCE, in the first competency it matches. There
# `incentives` is nearly co-extensive with "a watchdog published something", so
# without this the Incentives subsection restates most of Digital and Civil
# service — 22 slots for 15 events in the first week we tried it. The
# competencies it did not print under are shown on the item's meta line instead,
# so nothing is actually lost.
STATE_DEDUPE_ACROSS_SECTIONS = False
FEDERAL_DEDUPE_ACROSS_SECTIONS = True

# Display labels. The tables store slugs; an email is not the place for them.
COMMITTEE_LABELS = {
    "hsgac": "Senate HSGAC", "senate-rules": "Senate Rules",
    "senate-approps": "Senate Approps", "house-oversight": "House Oversight",
    "house-admin": "House Admin", "house-rules": "House Rules",
    "house-approps": "House Approps", "leadership": "Leadership",
    "gao": "GAO", "cbo": "CBO",
}
AGENCY_LABELS = {
    "opm": "OPM", "omb": "OMB", "gsa": "GSA", "white-house": "White House",
    "governmentwide": "Governmentwide", "gao": "GAO", "mspb": "MSPB",
    "flra": "FLRA", "oge": "OGE", "nara": "NARA", "oira": "OIRA",
    "dod": "DoD", "va": "VA", "ssa": "SSA", "hhs": "HHS", "cms": "CMS",
    "irs": "IRS", "treasury": "Treasury", "dhs": "DHS", "cisa": "CISA",
    "fema": "FEMA", "tsa": "TSA", "cbp-ice": "CBP/ICE", "state": "State Dept",
    "doj": "DOJ", "ed": "Education", "dol": "Labor", "doi": "Interior",
    "usda": "USDA", "doe": "Energy", "epa": "EPA", "hud": "HUD",
    "dot": "Transportation", "faa": "FAA", "sba": "SBA", "nasa": "NASA",
    "nsf": "NSF", "commerce": "Commerce", "nist": "NIST", "census": "Census",
    "eac": "EAC", "fcc": "FCC", "ftc": "FTC", "sec": "SEC", "nrc": "NRC",
    "usaid": "USAID", "usps": "USPS", "courts": "Federal courts", "other": "Other",
}
LANE_LABELS = {
    "executive-action": "agency action", "oversight": "watchdog",
    "news": "reported", "rulemaking": "rulemaking",
}


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #

def date_epoch(iso: str) -> int:
    """ISO date (YYYY-MM-DD) -> epoch days, for sorting. 0 if unparseable."""
    try:
        return (datetime.strptime(iso, "%Y-%m-%d").date() - date(1970, 1, 1)).days
    except (ValueError, TypeError):
        return 0


def window_cutoff(days: int, since: str | None) -> str:
    return since or (date.today() - timedelta(days=days)).isoformat()


def api_base():
    if not all([AIRTABLE_TOKEN, AIRTABLE_BASE_ID]):
        sys.exit("Missing AIRTABLE_TOKEN / AIRTABLE_BASE_ID; see .env_example.")
    return Api(AIRTABLE_TOKEN)


def read_table(name: str) -> list[dict]:
    """All rows of a table as field dicts. A table that doesn't exist yet (a
    pipeline that has never run) yields nothing rather than killing the digest —
    the whole point of one email is that a missing half degrades gracefully."""
    try:
        return [r["fields"] for r in api_base().table(AIRTABLE_BASE_ID, name).all()]
    except Exception as e:
        print(f"  (skipping {name}: {e})")
        return []


def as_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def lines_of(value: str) -> list[str]:
    return [v.strip() for v in (value or "").splitlines() if v.strip()]


def commas_of(value: str) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def first_sentences(text: str, n: int = 2) -> str:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return " ".join(parts[:n]).strip()


def _domain(url: str) -> str:
    m = re.search(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1) if m else "link"


def outlet_summary(outlets: list[str], cap: int = 4) -> str:
    if not outlets:
        return ""
    shown = outlets[:cap]
    extra = len(outlets) - len(shown)
    return ", ".join(shown) + (f" +{extra} more" if extra > 0 else "")


def item(title, summary="", meta="", relevance=0, links=(), date_str="", sort_key=None):
    """The one shape every section renders through.

    `links` is a list of (label, url). `sort_key` lets a section override the
    default ordering without the renderer knowing anything about it.
    """
    return {
        "title": (title or "").strip(),
        "summary": (summary or "").strip(),
        "meta": (meta or "").strip(),
        "relevance": as_int(relevance),
        "links": list(links),
        "date": date_str,
        "sort_key": sort_key,
    }


def paired_links(urls: list[str], outlets: list[str], cap: int = 3) -> list[tuple[str, str]]:
    """(label, url) pairs, labelled by outlet where the lists line up and by
    hostname where they don't. Capped: a five-outlet cluster does not need five
    links in an email."""
    out = []
    for i, u in enumerate(urls[:cap]):
        label = outlets[i] if i < len(outlets) and outlets[i] else _domain(u)
        out.append((label, u))
    return out


def gov_press_links(urls: list[str], outlets: list[str]) -> list[tuple[str, str]]:
    """Federal events hold both the instrument and the reporting on it. Offer one
    of each — the same rule the web tab uses — rather than the first two URLs,
    which are often two write-ups of the same thing."""
    primary = [u for u in urls if ".gov" in _domain(u)]
    press = [u for u in urls if ".gov" not in _domain(u)]
    label_at = {u: (outlets[i] if i < len(outlets) and outlets[i] else _domain(u))
                for i, u in enumerate(urls)}
    picked = (primary[:1] + press[:1]) or []
    if len(picked) < 2:                    # all one kind — still offer two
        picked = (primary or press)[:2]
    return [(label_at.get(u) or _domain(u), u) for u in picked]


# --------------------------------------------------------------------------- #
# Loaders — one per clean table. Each returns rows in a common selection shape:
#   {competency: [...], relevance: int, article_count: int, date_epoch, item}
# so `select()` below is the only place selection logic lives.
# --------------------------------------------------------------------------- #

def _row(f, comp_field="competency"):
    return {
        "competency": f.get(comp_field) or [],
        "relevance": as_int(f.get("relevance")),
        "article_count": as_int(f.get("article_count"), 1),
        "date_epoch": date_epoch(f.get("date", "")),
    }


def load_state_events(days: int, since: str | None) -> list[dict]:
    cutoff = window_cutoff(days, since)
    out = []
    for f in read_table(EVENTS_TABLE):
        d = f.get("date", "")
        if not d or d < cutoff:
            continue
        urls = lines_of(f.get("source_urls"))
        outlets = commas_of(f.get("source_outlets"))
        title = re.sub(r"^[A-Z]{2} — ", "", (f.get("Name") or "").strip())
        summary = (f.get("why_it_matters") or "").strip() or first_sentences(f.get("Notes"), 2)
        meta = " · ".join(x for x in (f.get("state"), f.get("activity_type"),
                                      f.get("gov_actor")) if x)
        row = _row(f)
        row["item"] = item(title, summary, meta, row["relevance"],
                           paired_links(urls, outlets), d)
        out.append(row)
    return out


def load_congress_events(days: int, since: str | None) -> list[dict]:
    cutoff = window_cutoff(days, since)
    out = []
    for f in read_table(CONGRESS_EVENTS_TABLE):
        d = f.get("date", "")
        if not d or d < cutoff:
            continue
        urls = lines_of(f.get("source_urls"))
        outlets = lines_of(f.get("source_outlets"))
        summary = (f.get("why_it_matters") or "").strip() or first_sentences(f.get("summary"), 2)
        cmte = COMMITTEE_LABELS.get(f.get("committee"), f.get("committee") or "")
        meta = " · ".join(x for x in (cmte, f.get("activity_type"), f.get("actor")) if x)
        row = _row(f)
        row["item"] = item(f.get("short_title") or f.get("headline"), summary, meta,
                           row["relevance"], paired_links(urls, outlets), d)
        out.append(row)
    return out


def load_federal_events(days: int, since: str | None) -> list[dict]:
    cutoff = window_cutoff(days, since)
    out = []
    for f in read_table(FEDERAL_EVENTS_TABLE):
        d = f.get("date", "")
        if not d or d < cutoff:
            continue
        urls = lines_of(f.get("source_urls"))
        outlets = lines_of(f.get("source_outlets"))
        summary = (f.get("why_it_matters") or "").strip() or first_sentences(f.get("summary"), 2)
        agencies = [AGENCY_LABELS.get(a, a) for a in (f.get("agency") or [])][:2]
        bits = [", ".join(agencies)] if agencies else []
        if f.get("instrument_id"):
            bits.append(f["instrument_id"])
        elif f.get("instrument_type"):
            bits.append(f["instrument_type"])
        # `official` is the default and says nothing; the other two are the
        # reader's cue that no primary document exists yet.
        if f.get("verification") and f["verification"] != "official":
            bits.append(f["verification"])
        lane = LANE_LABELS.get(f.get("lane"), "")
        if lane:
            bits.append(lane)
        row = _row(f)
        row["item"] = item(f.get("short_title") or f.get("headline"), summary,
                           " · ".join(b for b in bits if b), row["relevance"],
                           gov_press_links(urls, outlets), d)
        out.append(row)
    return out


def load_hearings(days: int, since: str | None) -> tuple[list[dict], list[dict]]:
    """(upcoming, recently held). Upcoming ignores the window — a hearing next
    Tuesday is the single most perishable thing in this email and would fail a
    'last N days' test."""
    cutoff = window_cutoff(days, since)
    today = date.today().isoformat()
    upcoming, recent = [], []
    for f in read_table(CONGRESS_HEARINGS_TABLE):
        d = f.get("date", "")
        if not d:
            continue
        cmte = COMMITTEE_LABELS.get(f.get("committee"), f.get("committee") or "")
        when = datetime.strptime(d, "%Y-%m-%d").strftime("%a %b %-d") if len(d) >= 10 else d
        bits = [when, cmte]
        if f.get("meeting_type"):
            bits.append(f["meeting_type"])
        if f.get("hearing_status") and f["hearing_status"] not in ("held", "scheduled"):
            bits.append(f["hearing_status"])
        if f.get("location"):
            bits.append(f["location"])
        # Agenda first, why-it-matters second — the opposite of every other
        # section. A calendar entry should say what the hearing is about; the
        # interpretive line is written before anyone has heard the testimony and
        # often reads as the classifier thinking out loud.
        it = item(f.get("short_title") or f.get("title"),
                  first_sentences(f.get("agenda_summary"), 1)
                  or (f.get("why_it_matters") or "").strip(),
                  " · ".join(b for b in bits if b), as_int(f.get("relevance")),
                  paired_links(lines_of(f.get("source_urls")), ["Congress.gov"]), d)
        row = {"competency": f.get("competency") or [],
               "relevance": as_int(f.get("relevance")), "article_count": 1,
               "date_epoch": date_epoch(d), "item": it}
        if d >= today:
            upcoming.append(row)
        elif d >= cutoff:
            recent.append(row)
    upcoming.sort(key=lambda r: r["date_epoch"])                 # soonest first
    recent.sort(key=lambda r: -r["date_epoch"])                  # newest first
    return upcoming, recent


def load_bills(days: int, since: str | None) -> list[dict]:
    """Bills the committees actually moved. `referred` is excluded: it means the
    bill was handed to a committee, which happens to hundreds of bills and is not
    news. Marked up or reported is news."""
    cutoff = window_cutoff(days, since)
    out = []
    for f in read_table(CONGRESS_BILLS_TABLE):
        d = f.get("committee_action_date") or f.get("date") or ""
        if not d or d < cutoff:
            continue
        if (f.get("committee_action") or "") not in ("marked-up", "reported"):
            continue
        if as_int(f.get("relevance")) < 2 or not (f.get("competency") or []):
            continue
        cmte = COMMITTEE_LABELS.get(f.get("committee"), f.get("committee") or "")
        meta = " · ".join(x for x in (f.get("bill_number"), cmte,
                                      f.get("committee_action"), f.get("bill_status")) if x)
        it = item(f.get("title"),
                  (f.get("why_it_matters") or "").strip() or first_sentences(f.get("summary"), 1),
                  meta, as_int(f.get("relevance")),
                  paired_links(lines_of(f.get("source_urls")), ["Congress.gov"]), d)
        out.append({"competency": f.get("competency") or [],
                    "relevance": as_int(f.get("relevance")), "article_count": 1,
                    "date_epoch": date_epoch(d), "item": it})
    out.sort(key=lambda r: (-r["relevance"], -r["date_epoch"]))
    return out


# --------------------------------------------------------------------------- #
# Governors '26 — its own selection rule (race competitiveness, not competency)
# --------------------------------------------------------------------------- #

def is_competitive(rating: str) -> bool:
    r = (rating or "").strip()
    return r == "Toss-up" or r.startswith("Lean")


def load_roster() -> dict[tuple[str, str], dict]:
    roster = {}
    for f in read_table(CANDIDATES_TABLE):
        key = ((f.get("state") or "").strip().upper(), (f.get("candidate") or "").strip())
        roster[key] = {
            "race_type": (f.get("race_type") or "").strip(),
            "race_rating": (f.get("race_rating") or "").strip(),
            "party": (f.get("party") or "").strip(),
            "status": (f.get("status") or "").strip(),
        }
    return roster


def load_candidate_devs(days: int, since: str | None) -> list[dict]:
    """RA-relevant developments only (a competency was assigned)."""
    cutoff = window_cutoff(days, since)
    devs = []
    for f in read_table(CANDIDATE_EVENTS_TABLE):
        d = f.get("date", "")
        if not d or d < cutoff or not (f.get("competency") or []):
            continue
        devs.append({
            "candidate": (f.get("candidate") or "").strip(),
            "state": (f.get("state") or "").strip().upper(),
            "date": d,
            "date_epoch": date_epoch(d),
            "relevance": as_int(f.get("relevance")),
            "competency": f.get("competency") or [],
            "article_count": as_int(f.get("article_count"), 1),
            "headline": (f.get("headline") or "").strip(),
            "summary": (f.get("summary") or "").strip(),
            "why_it_matters": (f.get("why_it_matters") or "").strip(),
            "source_outlets": commas_of(f.get("source_outlets")),
            "source_urls": lines_of(f.get("source_urls")),
        })
    return devs


def dev_sources(d: dict) -> tuple[list[tuple[str, str]], list[str]]:
    """Candidate developments come from Google News, which yields long redirect
    URLs. Prefer real publisher links; if there are none, collapse every Google
    News URL to a single labelled link and list the publications alongside."""
    urls, outlets = d["source_urls"], d["source_outlets"]
    paired = [(urls[i], outlets[i] if i < len(outlets) else "") for i in range(len(urls))]
    non_gn = [(u, o) for (u, o) in paired if "news.google." not in u]
    if non_gn:
        return [(o or _domain(u), u) for (u, o) in non_gn][:3], []
    if urls:
        return [("Google News", urls[0])], outlets
    return [], []


def select_governors(devs: list[dict], roster: dict) -> tuple[list[dict], list[dict]]:
    """Two tiers, deliberately NOT by competency:
         tier 1 — an open-seat or competitive race, relevance >= 2
         tier 2 — anything else, only at relevance 3
    Defeated and withdrawn candidates are dropped: after a primary their platform
    is no longer news, and post-primary the roster carries the losers on purpose.
    """
    tier1, tier2 = [], []
    for d in devs:
        r = roster.get((d["state"], d["candidate"]), {})
        if r.get("status") in ("defeated", "withdrawn"):
            continue
        d["_rating"] = r.get("race_rating", "")
        d["_party"] = r.get("party", "")
        cand = d["candidate"] + (f" ({d['_party']})" if d["_party"] else "")
        bits = [b for b in (d["state"], cand, d["_rating"]) if b]
        if d["article_count"] > 1:
            bits.append(f"{d['article_count']} sources")
        links, names = dev_sources(d)
        summary = d["why_it_matters"] or first_sentences(d["summary"], 2)
        if names:
            summary = summary
        d["item"] = item(d["headline"], summary, " · ".join(bits), d["relevance"],
                         links, d["date"])
        d["item"]["outlet_note"] = outlet_summary(names)
        priority = r.get("race_type") == "open" or is_competitive(r.get("race_rating", ""))
        if priority and d["relevance"] >= 2:
            tier1.append(d)
        elif d["relevance"] >= 3:
            tier2.append(d)
    order = lambda d: (-d["relevance"], -d["article_count"], -d["date_epoch"])
    tier1.sort(key=order)
    tier2.sort(key=order)
    return tier1[:8], tier2[:5]


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #

def rank(r: dict):
    """Relevance-2 items get truncated, so order them most-covered then newest."""
    return (-r["article_count"], -r["date_epoch"])


def select(rows: list[dict], comp: str, cap: int = 5) -> list[dict]:
    """Every relevance-3 item in this competency, then the best 2s up to `cap`."""
    in_comp = [r for r in rows if comp in (r["competency"] or [])]
    threes = sorted((r for r in in_comp if r["relevance"] == 3), key=rank)
    twos = sorted((r for r in in_comp if r["relevance"] == 2), key=rank)
    selected = list(threes)
    for r in twos:
        if len(selected) >= cap:
            break
        selected.append(r)
    return selected


def select_by_competency(rows: list[dict], cap: int = 5,
                        dedupe: bool = False) -> dict[str, list[dict]]:
    """Per-competency selection in COMPETENCIES order.

    With `dedupe`, an event prints under the first competency it matches and
    carries the others on its meta line — see the constants above for why the
    two halves of the digest differ here.
    """
    out, seen = {}, set()
    for comp in COMPETENCIES:
        chosen = select(rows, comp, cap)
        if dedupe:
            chosen = [r for r in chosen if r["item"]["title"] not in seen]
            seen.update(r["item"]["title"] for r in chosen)
            for r in chosen:
                others = [COMPETENCY_LABELS[c].lower()
                          for c in COMPETENCIES
                          if c != comp and c in (r["competency"] or [])]
                if others:
                    r["item"]["also"] = "also " + " & ".join(others)
        out[comp] = chosen
    return out


def build(days: int, since: str | None) -> dict:
    """Everything the renderers need, in the order the email presents it."""
    state_rows = load_state_events(days, since)
    congress_rows = load_congress_events(days, since)
    federal_rows = load_federal_events(days, since)
    upcoming, recent = load_hearings(days, since)
    return {
        "state": {
            "by_comp": select_by_competency(
                state_rows, dedupe=STATE_DEDUPE_ACROSS_SECTIONS),
            "governors": select_governors(load_candidate_devs(days, since), load_roster()),
            "total": len(state_rows),
        },
        "federal": {
            "upcoming": upcoming[:8],
            "recent": recent[:4],
            "bills": load_bills(days, since)[:5],
            "congress_by_comp": select_by_competency(
                congress_rows, cap=4, dedupe=FEDERAL_DEDUPE_ACROSS_SECTIONS),
            "agency_by_comp": select_by_competency(
                federal_rows, cap=4, dedupe=FEDERAL_DEDUPE_ACROSS_SECTIONS),
            "total": len(congress_rows) + len(federal_rows),
        },
    }


# --------------------------------------------------------------------------- #
# HTML rendering
#
# Email HTML rules this follows, none of them optional:
#   * inline styles only — no <style> block survives Gmail reliably
#   * tables with bgcolor for the coloured section bars, because Outlook drops
#     background-color on a <div>
#   * explicit background on every container, or dark-mode clients invert the
#     text and leave the backgrounds alone
#   * no images and no web fonts: deliverability, and they don't load anyway
#   * 640px max width, 14px body, 1.5 line-height
# --------------------------------------------------------------------------- #

INK = "#0f172a"
MUTED = "#64748b"
FAINT = "#94a3b8"
RULE = "#e2e8f0"
PAGE_BG = "#f1f5f9"
CARD_BG = "#ffffff"
LINK = "#2563eb"

FONT = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,"
        "sans-serif")


def h_banner(label: str, blurb: str) -> str:
    """A full-width section bar. The two of these are the email's spine — the
    reader should never have to work out which half they are in."""
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="margin:34px 0 0;"><tr>'
        f'<td bgcolor="{INK}" style="background-color:{INK};padding:11px 16px;'
        f'border-radius:6px 6px 0 0;">'
        f'<div style="font-family:{FONT};font-size:15px;font-weight:700;color:#ffffff;'
        f'letter-spacing:.10em;text-transform:uppercase;">{escape(label)}</div>'
        f'</td></tr><tr><td bgcolor="#f8fafc" style="background-color:#f8fafc;'
        f'padding:8px 16px;border-left:1px solid {RULE};border-right:1px solid {RULE};'
        f'border-bottom:1px solid {RULE};">'
        f'<div style="font-family:{FONT};font-size:12.5px;color:{MUTED};line-height:1.45;">'
        f'{blurb}</div></td></tr></table>'
    )


def h_subhead(label: str, blurb: str = "") -> str:
    """Branch-level header inside a section (Congress / Agencies)."""
    out = (f'<div style="font-family:{FONT};font-size:14px;font-weight:700;color:{INK};'
           f'margin:26px 0 2px;">{escape(label)}</div>')
    if blurb:
        out += (f'<div style="font-family:{FONT};font-size:12px;color:{MUTED};'
                f'margin:0 0 10px;line-height:1.45;">{blurb}</div>')
    return out


def h_comp_head(comp: str) -> str:
    """Competency header, carrying the tracker's colour for that competency."""
    color = COMPETENCY_COLORS[comp]
    return (f'<div style="font-family:{FONT};font-size:11.5px;font-weight:700;'
            f'color:{color};text-transform:uppercase;letter-spacing:.07em;'
            f'border-bottom:2px solid {color};padding-bottom:3px;margin:18px 0 10px;">'
            f'{escape(COMPETENCY_LABELS[comp])}</div>')


def h_empty(text: str) -> str:
    return (f'<div style="font-family:{FONT};font-size:13px;color:{FAINT};'
            f'margin:0 0 8px;">{escape(text)}</div>')


def h_item(it: dict, accent: str = RULE) -> str:
    """One item card. The accent stripe ties an item to its competency colour and
    gives the eye a left edge to run down when scanning."""
    first = it["links"][0][1] if it["links"] else ""
    title = escape(it["title"])
    if first:
        title = (f'<a href="{escape(first)}" style="color:{INK};text-decoration:none;">'
                 f'{title}</a>')
    out = [f'<div style="border-left:3px solid {accent};padding:0 0 0 11px;'
           f'margin:0 0 15px;">']
    out.append(f'<div style="font-family:{FONT};font-size:14px;font-weight:700;'
               f'color:{INK};line-height:1.35;">{title}</div>')
    if it["summary"]:
        out.append(f'<div style="font-family:{FONT};font-size:13px;color:#334155;'
                   f'line-height:1.5;margin:3px 0 0;">{escape(it["summary"])}</div>')
    meta = it["meta"]
    if it.get("also"):
        meta = f'{meta} · {it["also"]}' if meta else it["also"]
    if meta:
        out.append(f'<div style="font-family:{FONT};font-size:11.5px;color:{MUTED};'
                   f'margin:4px 0 0;">{escape(meta)}</div>')
    if it["links"]:
        anchors = " · ".join(
            f'<a href="{escape(u)}" style="color:{LINK};text-decoration:none;">'
            f'{escape(label)}</a>' for label, u in it["links"])
        note = it.get("outlet_note")
        tail = f' <span style="color:{FAINT};">· {escape(note)}</span>' if note else ""
        out.append(f'<div style="font-family:{FONT};font-size:11.5px;margin:4px 0 0;">'
                   f'{anchors}{tail}</div>')
    out.append('</div>')
    return "".join(out)


def h_calendar(upcoming: list[dict], recent: list[dict]) -> str:
    """The calendar block. Given its own tinted panel because it is the one part
    of the email with a deadline attached."""
    out = [f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
           f'border="0" style="margin:20px 0 4px;"><tr>'
           f'<td bgcolor="#fffbeb" style="background-color:#fffbeb;padding:14px 16px;'
           f'border:1px solid #fde68a;border-radius:6px;">']
    out.append(f'<div style="font-family:{FONT};font-size:11.5px;font-weight:700;'
               f'color:#92400e;text-transform:uppercase;letter-spacing:.07em;'
               f'margin:0 0 10px;">On the calendar</div>')
    if upcoming:
        for r in upcoming:
            out.append(h_item(r["item"], "#f59e0b"))
    else:
        out.append(h_empty("Nothing scheduled. Congress posts most hearings about a "
                           "week out, and nothing during recess."))
    if recent:
        out.append(f'<div style="font-family:{FONT};font-size:11px;font-weight:700;'
                   f'color:{MUTED};text-transform:uppercase;letter-spacing:.06em;'
                   f'margin:14px 0 8px;">Recently held</div>')
        for r in recent:
            out.append(h_item(r["item"], "#fde68a"))
    out.append('</td></tr></table>')
    return "".join(out)


def h_by_competency(by_comp: dict[str, list[dict]], skip_empty: bool) -> str:
    """Competency subsections.

    `skip_empty` is False for STATE — showing all four every week is the rhythm
    readers learn — and True for the two FEDERAL branches, where eight
    subsections across two branches would otherwise print a wall of "nothing".
    """
    out = []
    for comp in COMPETENCIES:
        rows = by_comp.get(comp) or []
        if not rows and skip_empty:
            continue
        out.append(h_comp_head(comp))
        if not rows:
            out.append(h_empty("Nothing notable last week."))
            continue
        for r in rows:
            out.append(h_item(r["item"], COMPETENCY_COLORS[comp]))
    return "".join(out)


def render_html(d: dict, generated_on: date, window_days: int) -> str:
    state, fed = d["state"], d["federal"]
    n_state = sum(len(v) for v in state["by_comp"].values())
    n_gov = len(state["governors"][0]) + len(state["governors"][1])
    n_cong = sum(len(v) for v in fed["congress_by_comp"].values())
    n_agency = sum(len(v) for v in fed["agency_by_comp"].values())

    out = [f'<div style="background-color:{PAGE_BG};padding:20px 0;">',
           f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
           f'border="0"><tr><td align="center">',
           f'<table role="presentation" width="640" cellpadding="0" cellspacing="0" '
           f'border="0" style="max-width:640px;width:100%;">',
           f'<tr><td bgcolor="{CARD_BG}" style="background-color:{CARD_BG};'
           f'padding:26px 24px 28px;border-radius:8px;">']

    # --- masthead
    out.append(f'<div style="font-family:{FONT};font-size:22px;font-weight:700;'
               f'color:{INK};letter-spacing:-.01em;margin:0 0 3px;">'
               f'Capacity Digest</div>')
    out.append(f'<div style="font-family:{FONT};font-size:12px;color:{MUTED};'
               f'margin:0 0 16px;">{generated_on.strftime("%B %-d, %Y")} · '
               f'the last {window_days} days</div>')
    out.append(f'<div style="font-family:{FONT};font-size:14px;color:#334155;'
               f'line-height:1.55;margin:0 0 18px;">{escape(INTRO)}</div>')

    # --- what's inside: orients the reader before the first banner
    out.append(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
               f'border="0"><tr><td style="border-top:1px solid {RULE};'
               f'border-bottom:1px solid {RULE};padding:11px 0;">'
               f'<div style="font-family:{FONT};font-size:12px;color:{MUTED};'
               f'line-height:1.7;">'
               f'<strong style="color:{INK};">State</strong> — {n_state} '
               f'event{"" if n_state == 1 else "s"} across the four competencies'
               f'{f", {n_gov} from the 2026 governors&rsquo; races" if n_gov else ""}<br>'
               f'<strong style="color:{INK};">Federal</strong> — '
               f'{len(fed["upcoming"])} hearing{"" if len(fed["upcoming"]) == 1 else "s"} '
               f'coming up, {n_cong} from Congress, {n_agency} from the agencies'
               f'</div></td></tr></table>')

    # --- STATE
    out.append(h_banner("State", "What state governments did to their own capacity, "
                                 "by competency &mdash; plus the 2026 races."))
    out.append(h_by_competency(state["by_comp"], skip_empty=False))

    tier1, tier2 = state["governors"]
    out.append(h_subhead("Governors ’26",
                         "What candidates are saying and doing on state capacity. "
                         "Open-seat and competitive races first."))
    if not tier1 and not tier2:
        out.append(h_empty("Nothing notable from the 2026 races last week."))
    else:
        for dv in tier1:
            out.append(h_item(dv["item"], "#0ea5e9"))
        if tier2:
            out.append(f'<div style="font-family:{FONT};font-size:11px;font-weight:700;'
                       f'color:{MUTED};text-transform:uppercase;letter-spacing:.06em;'
                       f'margin:12px 0 9px;">Also notable elsewhere</div>')
            for dv in tier2:
                out.append(h_item(dv["item"], "#bae6fd"))

    # --- FEDERAL
    out.append(h_banner("Federal", "Washington on itself: what Congress moved, and what "
                                   "the agencies issued."))
    out.append(h_calendar(fed["upcoming"], fed["recent"]))

    if fed["bills"]:
        out.append(h_subhead("Bills the committees moved",
                             "Marked up or reported out this week &mdash; not merely "
                             "referred."))
        for r in fed["bills"]:
            out.append(h_item(r["item"], "#7c3aed"))

    out.append(h_subhead("Congress",
                         "Committee and member activity, scored against the same four "
                         "competencies pointed at the federal government."))
    if n_cong:
        out.append(h_by_competency(fed["congress_by_comp"], skip_empty=True))
    else:
        out.append(h_empty("Nothing notable from the committees last week — most often "
                           "the calendar rather than the pipeline."))

    out.append(h_subhead("Agencies & the executive branch",
                         "Memos, rules, guidance, workforce and procurement actions, "
                         "launches and watchdog findings."))
    if n_agency:
        out.append(h_by_competency(fed["agency_by_comp"], skip_empty=True))
    else:
        out.append(h_empty("Nothing notable from the agencies last week."))

    # --- footer
    out.append(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
               f'border="0" style="margin-top:28px;"><tr>'
               f'<td style="border-top:1px solid {RULE};padding-top:14px;">'
               f'<a href="{escape(TRACKER_URL)}" style="font-family:{FONT};font-size:13px;'
               f'color:{LINK};text-decoration:none;font-weight:600;">'
               f'See the full tracker &rarr;</a>'
               f'</td></tr></table>')

    out.append('</td></tr></table></td></tr></table></div>')
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Plain-text rendering — the same structure, so a text-only client gets the same
# email rather than a degraded one.
# --------------------------------------------------------------------------- #

def t_item(it: dict, indent: str = "") -> list[str]:
    lines = [f"{indent}- {it['title']}"]
    if it["summary"]:
        lines.append(f"{indent}  {it['summary']}")
    meta = it["meta"]
    if it.get("also"):
        meta = f"{meta} · {it['also']}" if meta else it["also"]
    if meta:
        lines.append(f"{indent}  {meta}")
    for label, u in it["links"]:
        note = it.get("outlet_note")
        lines.append(f"{indent}  {label}{f' ({note})' if note else ''}: {u}")
    lines.append("")
    return lines


def t_by_competency(by_comp: dict[str, list[dict]], skip_empty: bool) -> list[str]:
    lines = []
    for comp in COMPETENCIES:
        rows = by_comp.get(comp) or []
        if not rows and skip_empty:
            continue
        lines.append(f"-- {COMPETENCY_LABELS[comp].upper()} --")
        lines.append("")
        if not rows:
            lines += ["Nothing notable last week.", ""]
            continue
        for r in rows:
            lines += t_item(r["item"])
    return lines


def render_text(d: dict, generated_on: date, window_days: int) -> str:
    state, fed = d["state"], d["federal"]
    lines = ["CAPACITY DIGEST",
             f"{generated_on.strftime('%B %-d, %Y')} · the last {window_days} days",
             "", INTRO, ""]

    lines += ["=" * 62, "STATE", "=" * 62,
              "What state governments did to their own capacity, by competency.", ""]
    lines += t_by_competency(state["by_comp"], skip_empty=False)

    tier1, tier2 = state["governors"]
    lines += ["-- GOVERNORS '26 --",
              "What candidates are saying and doing on state capacity.", ""]
    if not tier1 and not tier2:
        lines += ["Nothing notable from the 2026 races last week.", ""]
    else:
        for dv in tier1:
            lines += t_item(dv["item"])
        if tier2:
            lines += ["   Also notable elsewhere:", ""]
            for dv in tier2:
                lines += t_item(dv["item"], indent="   ")

    lines += ["=" * 62, "FEDERAL", "=" * 62,
              "Washington on itself: what Congress moved, and what the agencies issued.",
              ""]
    lines += ["-- ON THE CALENDAR --", ""]
    if fed["upcoming"]:
        for r in fed["upcoming"]:
            lines += t_item(r["item"])
    else:
        lines += ["Nothing scheduled. Congress posts most hearings about a week out.", ""]
    if fed["recent"]:
        lines += ["   Recently held:", ""]
        for r in fed["recent"]:
            lines += t_item(r["item"], indent="   ")

    if fed["bills"]:
        lines += ["-- BILLS THE COMMITTEES MOVED --", ""]
        for r in fed["bills"]:
            lines += t_item(r["item"])

    lines += ["-- CONGRESS --", ""]
    if any(fed["congress_by_comp"].values()):
        lines += t_by_competency(fed["congress_by_comp"], skip_empty=True)
    else:
        lines += ["Nothing notable from the committees last week.", ""]

    lines += ["-- AGENCIES & THE EXECUTIVE BRANCH --", ""]
    if any(fed["agency_by_comp"].values()):
        lines += t_by_competency(fed["agency_by_comp"], skip_empty=True)
    else:
        lines += ["Nothing notable from the agencies last week.", ""]

    lines += [f"See the full tracker: {TRACKER_URL}"]
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# Sending
# --------------------------------------------------------------------------- #

def get_recipients(override: str | None) -> list[str]:
    return [override] if override else RECIPIENTS


def send_email(subject: str, html: str, text: str, recipients: list[str]) -> None:
    if not RESEND_API_KEY:
        sys.exit("Missing RESEND_API_KEY; see digest_feature_brief.md §6.")
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                 "Content-Type": "application/json"},
        json={"from": DIGEST_FROM, "to": recipients, "subject": subject,
              "html": html, "text": text},
        timeout=30,
    )
    if not (200 <= resp.status_code < 300):
        # A 403 here usually means the recipient isn't the Resend account address
        # and the sending domain isn't verified yet.
        raise RuntimeError(f"Resend send failed: HTTP {resp.status_code} — {resp.text}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def print_dry_run(d: dict, cutoff: str, window_days: int) -> None:
    state, fed = d["state"], d["federal"]
    print(f"Window: since {cutoff} ({window_days} days)")
    print(f"Subject: {SUBJECT}\n")

    print("=" * 60)
    print(f"STATE  ({state['total']} events in window)")
    print("=" * 60)
    for comp in COMPETENCIES:
        rows = state["by_comp"][comp]
        n3 = sum(1 for r in rows if r["relevance"] == 3)
        n2 = sum(1 for r in rows if r["relevance"] == 2)
        print(f"[{COMPETENCY_LABELS[comp]}] {len(rows)} selected ({n3}x3 + {n2}x2)")
        for r in rows:
            print(f"    {'●' * r['relevance']:<3} {r['item']['title'][:66]}")
        if not rows:
            print("    (nothing notable)")
    tier1, tier2 = state["governors"]
    print(f"[Governors '26] {len(tier1)} priority + {len(tier2)} other")
    for dv in tier1 + tier2:
        print(f"    {'●' * dv['relevance']:<3} {dv['state']:<3} "
              f"{dv['candidate']:<20} {dv['item']['title'][:44]}")

    print("\n" + "=" * 60)
    print(f"FEDERAL  ({fed['total']} events in window)")
    print("=" * 60)
    print(f"[On the calendar] {len(fed['upcoming'])} upcoming, {len(fed['recent'])} recent")
    for r in fed["upcoming"] + fed["recent"]:
        print(f"    {r['item']['meta'][:34]:<36} {r['item']['title'][:44]}")
    print(f"[Bills moved] {len(fed['bills'])}")
    for r in fed["bills"]:
        print(f"    {'●' * r['relevance']:<3} {r['item']['title'][:66]}")
    for label, key in (("Congress", "congress_by_comp"), ("Agencies", "agency_by_comp")):
        total = sum(len(v) for v in fed[key].values())
        print(f"[{label}] {total} selected")
        for comp in COMPETENCIES:
            rows = fed[key][comp]
            if not rows:
                continue
            print(f"   {COMPETENCY_LABELS[comp]}:")
            for r in rows:
                print(f"    {'●' * r['relevance']:<3} {r['item']['title'][:62]}")
    print("\n--- dry run: no email sent ---")


def main() -> None:
    ap = argparse.ArgumentParser(description="Send the weekly capacity email digest.")
    ap.add_argument("--days", type=int, default=7, help="Digest window (default 7).")
    ap.add_argument("--since", default=None, metavar="YYYY-MM-DD",
                    help="Anchor the window to this date instead of --days back.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Render + per-section counts to stdout; send nothing.")
    ap.add_argument("--html-out", default=None, metavar="PATH",
                    help="Write the rendered HTML to a file and STOP. Writing a "
                         "preview is a look-before-you-send action, so it never "
                         "sends; add --send to do both.")
    ap.add_argument("--send", action="store_true",
                    help="Send even when --html-out was given.")
    ap.add_argument("--to", default=None, help="Override recipient (post-DNS only).")
    args = ap.parse_args()

    generated_on = date.today()
    cutoff = window_cutoff(args.days, args.since)
    window_days = (generated_on - date.fromisoformat(cutoff)).days

    d = build(args.days, args.since)
    html = render_html(d, generated_on, window_days)
    text = render_text(d, generated_on, window_days)

    if args.html_out:
        with open(args.html_out, "w") as f:
            f.write(html)
        print(f"Wrote {args.html_out} ({len(html) / 1024:.0f} KB)")

    if args.dry_run:
        print_dry_run(d, cutoff, window_days)
        return

    # Rendering a preview implies you want to look at it before it goes out.
    # This defaults to NOT sending because the alternative failed live: a
    # --html-out run with no --dry-run mailed a real digest.
    if args.html_out and not args.send:
        print("(preview written — nothing sent; add --send to send as well)")
        return

    recipients = get_recipients(args.to)
    send_email(SUBJECT, html, text, recipients)
    total = d["state"]["total"] + d["federal"]["total"]
    print(f"Sent digest ({total} events in window) to {', '.join(recipients)} "
          f"from {DIGEST_FROM}")


if __name__ == "__main__":
    main()
