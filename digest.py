#!/usr/bin/env python3
"""State Activity Tracker — weekly email digest.

Runs right after dedupe.py each week: reads the last N days of the clean
'Events' table, selects the most notable events per competency (see §3 of
digest_feature_brief.md), composes one HTML+text email, and sends it via Resend.

Phase 1: single hard-coded recipient (the Resend account address), sending from
Resend's pre-verification sender. The recipient source (get_recipients) and the
provider call (send_email) are isolated so a subscriber model / real domain can
drop in later without touching selection or formatting.

Usage:
    python digest.py --days 7              # compose + send to RECIPIENTS
    python digest.py --days 7 --dry-run    # render + per-category counts, send nothing
    python digest.py --days 7 --to me@x.com  # override recipient (post-DNS only)
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
# The clean, deduped candidates layer (candidates_dedupe.py) + the roster, for
# the "Gov Candidates Corner" section at the foot of the digest.
CANDIDATE_EVENTS_TABLE = "Candidate Events"
CANDIDATES_TABLE = "Gov Candidates"

# Public read-only tracker (overridable via env). Linked at the foot of the digest.
TRACKER_URL = os.environ.get("TRACKER_URL", "https://state-tracker-e2i7.vercel.app/")

# Fixed subject line for every send (no date/count, per request).
SUBJECT = "State Activity Digest from Last Week"

# Snippy opener.
INTRO = ("Here's everything you need to know about what states got up to last week "
         "in the world of state capacity.")

# §0 pre-DNS constraint: Resend can only deliver to the account's own address
# until a domain is verified. Do not add other recipients yet — they 403.
RECIPIENTS = ["atharv@recodingamerica.fund"]

# §3 — fixed section order; values match the Events `competency` field exactly.
COMPETENCIES = ["civil-service", "procedure", "digital", "incentives"]
COMPETENCY_LABELS = {
    "civil-service": "Civil service",
    "procedure": "Procedure",
    "digital": "Digital",
    "incentives": "Incentives",
}

# §4 — an event spanning two competencies appears in each relevant section.
# Flip to True later to show it only in its first section.
DEDUPE_ACROSS_SECTIONS = False


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #

def date_epoch(iso: str) -> int:
    """ISO date (YYYY-MM-DD) -> epoch days, for sorting. 0 if unparseable."""
    try:
        return (datetime.strptime(iso, "%Y-%m-%d").date() - date(1970, 1, 1)).days
    except (ValueError, TypeError):
        return 0


def window_cutoff(days: int, since: str | None) -> str:
    """The ISO date on/after which rows are kept: an explicit --since date if
    given, else `days` back from today."""
    return since or (date.today() - timedelta(days=days)).isoformat()


def load_events(days: int, since: str | None = None) -> list[dict]:
    """Read the Events table, keep rows dated on/after the window cutoff."""
    if not all([AIRTABLE_TOKEN, AIRTABLE_BASE_ID]):
        sys.exit("Missing AIRTABLE_TOKEN / AIRTABLE_BASE_ID; see .env_example.")
    api = Api(AIRTABLE_TOKEN)
    table = api.table(AIRTABLE_BASE_ID, EVENTS_TABLE)
    cutoff = window_cutoff(days, since)

    events = []
    for rec in table.all():
        f = rec["fields"]
        d = f.get("date", "")
        if not d or d < cutoff:
            continue
        outlets = [o.strip() for o in (f.get("source_outlets") or "").split(",") if o.strip()]
        urls = [u.strip() for u in (f.get("source_urls") or "").splitlines() if u.strip()]
        rel = f.get("relevance")
        try:
            rel = int(rel)
        except (TypeError, ValueError):
            rel = 0
        events.append({
            "name": (f.get("Name") or "").strip(),
            "competency": f.get("competency") or [],
            "relevance": rel,
            "article_count": int(f.get("article_count") or 1),
            "date": d,
            "date_epoch": date_epoch(d),
            "state": f.get("state") or "",
            "activity_type": f.get("activity_type") or "",
            "gov_actor": f.get("gov_actor") or "",
            "why_it_matters": (f.get("why_it_matters") or "").strip(),
            "notes": (f.get("Notes") or "").strip(),
            "source_outlets": outlets,
            "source_urls": urls,
        })
    return events


# --------------------------------------------------------------------------- #
# Gov Candidates Corner (§ candidate developments) — separate table + roster
# --------------------------------------------------------------------------- #

def is_competitive(rating: str) -> bool:
    """Cook/Sabato consensus rating counts as competitive if it's a Toss-up or
    a Lean. Mirrors the web tab's ratingClass() != 'settled' test."""
    r = (rating or "").strip()
    return r == "Toss-up" or r.startswith("Lean")


def load_roster() -> dict[tuple[str, str], dict]:
    """(state, candidate) -> {race_type, race_rating, party, role}. Lets the
    corner know which developments belong to open-seat / competitive races."""
    api = Api(AIRTABLE_TOKEN)
    table = api.table(AIRTABLE_BASE_ID, CANDIDATES_TABLE)
    roster = {}
    for rec in table.all():
        f = rec["fields"]
        key = ((f.get("state") or "").strip().upper(), (f.get("candidate") or "").strip())
        roster[key] = {
            "race_type": (f.get("race_type") or "").strip(),
            "race_rating": (f.get("race_rating") or "").strip(),
            "party": (f.get("party") or "").strip(),
            "role": (f.get("current_role") or "").strip(),
        }
    return roster


def load_candidate_devs(days: int, since: str | None = None) -> list[dict]:
    """Read the clean 'Candidate Events' table, keep RAF-relevant developments
    (a competency was assigned) dated on/after the window cutoff. Missing table
    (no dedupe run yet) -> empty, so the digest still sends."""
    api = Api(AIRTABLE_TOKEN)
    table = api.table(AIRTABLE_BASE_ID, CANDIDATE_EVENTS_TABLE)
    cutoff = window_cutoff(days, since)

    devs = []
    try:
        records = table.all()
    except Exception:
        return devs
    for rec in records:
        f = rec["fields"]
        d = f.get("date", "")
        if not d or d < cutoff:
            continue
        comp = f.get("competency") or []
        if not comp:                       # RAF-relevant only
            continue
        try:
            rel = int(f.get("relevance") or 0)
        except (TypeError, ValueError):
            rel = 0
        outlets = [o.strip() for o in (f.get("source_outlets") or "").split(",") if o.strip()]
        urls = [u.strip() for u in (f.get("source_urls") or "").splitlines() if u.strip()]
        devs.append({
            "candidate": (f.get("candidate") or "").strip(),
            "state": (f.get("state") or "").strip().upper(),
            "date": d,
            "date_epoch": date_epoch(d),
            "relevance": rel,
            "competency": comp,
            "article_count": int(f.get("article_count") or 1),
            "headline": (f.get("headline") or "").strip(),
            "summary": (f.get("summary") or "").strip(),
            "why_it_matters": (f.get("why_it_matters") or "").strip(),
            "source_outlets": outlets,
            "source_urls": urls,
        })
    return devs


def select_candidate_corner(devs: list[dict], roster: dict) -> tuple[list[dict], list[dict]]:
    """Two tiers, NOT grouped by competency (per request):
      tier 1 — developments in an open-seat OR competitive race, relevance >= 2;
      tier 2 — anything else, only if relevance == 3 (noteworthy elsewhere).
    Each tier ordered by relevance, then coverage, then recency. The race
    rating/party is attached to each dev for rendering."""
    tier1, tier2 = [], []
    for d in devs:
        r = roster.get((d["state"], d["candidate"]), {})
        d["_rating"] = r.get("race_rating", "")
        d["_party"] = r.get("party", "")
        priority = r.get("race_type") == "open" or is_competitive(r.get("race_rating", ""))
        if priority and d["relevance"] >= 2:
            tier1.append(d)
        elif d["relevance"] >= 3:
            tier2.append(d)
    order = lambda d: (-d["relevance"], -d["article_count"], -d["date_epoch"])
    tier1.sort(key=order)
    tier2.sort(key=order)
    return tier1[:10], tier2[:6]


# --------------------------------------------------------------------------- #
# Selection (§3 / §4)
# --------------------------------------------------------------------------- #

def rank(e: dict):
    """§4: 2's ordered most-covered then most-recent (they get truncated)."""
    return (-e["article_count"], -e["date_epoch"])


def select(events: list[dict], comp: str) -> list[dict]:
    in_comp = [e for e in events if comp in (e["competency"] or [])]
    threes = [e for e in in_comp if e["relevance"] == 3]
    twos = sorted((e for e in in_comp if e["relevance"] == 2), key=rank)
    selected = list(threes)                 # all 3's, unconditionally
    i = 0
    while len(selected) <= 4 and i < len(twos):
        selected.append(twos[i])
        i += 1
    return selected


def select_all(events: list[dict]) -> dict[str, list[dict]]:
    """Per-competency selection, honoring DEDUPE_ACROSS_SECTIONS."""
    out = {}
    seen = set()
    for comp in COMPETENCIES:
        chosen = select(events, comp)
        if DEDUPE_ACROSS_SECTIONS:
            chosen = [e for e in chosen if e["name"] not in seen]
            seen.update(e["name"] for e in chosen)
        out[comp] = chosen
    return out


def first_sentences(text: str, n: int = 2) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(parts[:n]).strip()


def summary_of(e: dict) -> str:
    """§4: why_it_matters if present, else the first 1-2 sentences of Notes."""
    if e["why_it_matters"]:
        return e["why_it_matters"]
    if e["notes"]:
        return first_sentences(e["notes"], 2)
    return ""


# --------------------------------------------------------------------------- #
# Rendering (§5)
# --------------------------------------------------------------------------- #

def monday_of_this_week() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


def meta_line(e: dict) -> str:
    bits = [b for b in (e["state"], e["activity_type"], e["gov_actor"]) if b]
    return " · ".join(bits)


def dev_summary(d: dict) -> str:
    if d["why_it_matters"]:
        return d["why_it_matters"]
    if d["summary"]:
        return first_sentences(d["summary"], 2)
    return ""


def _domain(url: str) -> str:
    m = re.search(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1) if m else "link"


def outlet_summary(outlets: list[str], cap: int = 4) -> str:
    """'12News, Arizona Mirror, Focus Gaming News +3 more' — readable, capped."""
    if not outlets:
        return ""
    shown = outlets[:cap]
    extra = len(outlets) - len(shown)
    return ", ".join(shown) + (f" +{extra} more" if extra > 0 else "")


def dev_sources(d: dict) -> tuple[list[tuple[str, str]], list[str]]:
    """Resolve a development's source links (candidate devs come from Google News,
    which yields long news.google.com redirect URLs). Returns
    (links, outlet_names): if any real (non-Google-News) URL exists, use those and
    DROP the Google News ones; otherwise collapse all Google News URLs to a single
    ('Google News', first_url) link. outlet_names is the readable publication list
    for display alongside a collapsed link."""
    urls = d["source_urls"]
    outlets = d["source_outlets"]
    paired = [(urls[i], outlets[i] if i < len(outlets) else "") for i in range(len(urls))]
    non_gn = [(u, o) for (u, o) in paired if "news.google." not in u]
    if non_gn:
        return [(o or _domain(u), u) for (u, o) in non_gn], []
    if urls:
        return [("Google News", urls[0])], outlets
    return [], []


def dev_meta_line(d: dict) -> str:
    cand = d["candidate"] + (f" ({d['_party']})" if d.get("_party") else "")
    bits = [b for b in (d["state"], cand, d.get("_rating") or "") if b]
    src = f"{d['article_count']} sources" if d["article_count"] > 1 else ""
    if src:
        bits.append(src)
    return " · ".join(bits)


def render_dev_text(d: dict) -> list[str]:
    lines = [f"- {d['headline']}  {'●' * d['relevance']}"]
    s = dev_summary(d)
    if s:
        lines.append(f"  {s}")
    ml = dev_meta_line(d)
    if ml:
        lines.append(f"  {ml}")
    links, names = dev_sources(d)
    for label, u in links:
        summary = outlet_summary(names)
        suffix = f" ({summary})" if summary else ""
        lines.append(f"  {label}{suffix}: {u}")
    lines.append("")
    return lines


def render_text(sections: dict[str, list[dict]], corner: tuple[list[dict], list[dict]],
                generated_on: date, window_days: int) -> str:
    lines = ["State Activity Digest from Last Week",
             f"Generated on {generated_on.strftime('%b %-d, %Y')} · "
             f"pulling from the last {window_days} days",
             "", INTRO, ""]
    for comp in COMPETENCIES:
        lines.append(f"== {COMPETENCY_LABELS[comp]} ==")
        evs = sections[comp]
        if not evs:
            lines.append("Nothing notable last week.")
            lines.append("")
            continue
        for e in evs:
            dots = "●" * e["relevance"]
            title = re.sub(r"^[A-Z]{2} — ", "", e["name"])
            lines.append(f"- {title}  {dots}")
            s = summary_of(e)
            if s:
                lines.append(f"  {s}")
            ml = meta_line(e)
            if ml:
                lines.append(f"  {ml}")
            for i, u in enumerate(e["source_urls"]):
                label = e["source_outlets"][i] if i < len(e["source_outlets"]) else u
                lines.append(f"  {label}: {u}")
            lines.append("")

    tier1, tier2 = corner
    lines.append("== Gov Candidates Corner ==")
    lines.append("The 2026 governors' races — what candidates are saying and doing "
                 "on state capacity.")
    lines.append("")
    if not tier1 and not tier2:
        lines.append("Nothing notable from the 2026 races last week.")
        lines.append("")
    else:
        for d in tier1:
            lines += render_dev_text(d)
        if tier2:
            lines.append("-- Also notable elsewhere --")
            lines.append("")
            for d in tier2:
                lines += render_dev_text(d)

    lines.append(f"See the full tracker: {TRACKER_URL}")
    return "\n".join(lines).rstrip() + "\n"


def render_dev_html(d: dict) -> list[str]:
    first_url = d["source_urls"][0] if d["source_urls"] else ""
    title = escape(d["headline"])
    title_html = (f'<a href="{escape(first_url)}" style="color:#0f172a;'
                  f'text-decoration:none;">{title}</a>' if first_url else title)
    dots = "●" * d["relevance"]
    out = ['<div style="margin:0 0 16px;">']
    out.append(f'<div style="font-weight:700;font-size:14px;">{title_html} '
               f'<span style="color:#f59e0b;font-size:11px;">{dots}</span></div>')
    s = dev_summary(d)
    if s:
        out.append(f'<div style="font-size:13px;color:#334155;line-height:1.5;'
                   f'margin:3px 0;">{escape(s)}</div>')
    ml = dev_meta_line(d)
    if ml:
        out.append(f'<div style="font-size:12px;color:#64748b;">{escape(ml)}</div>')
    links, names = dev_sources(d)
    anchors = [f'<a href="{escape(u)}" style="color:#2563eb;text-decoration:none;">'
               f'{escape(label)}</a>' for label, u in links]
    if anchors:
        summary = outlet_summary(names)
        tail = (f' <span style="color:#94a3b8;">· {escape(summary)}</span>'
                if summary else "")
        out.append(f'<div style="font-size:12px;margin-top:2px;">'
                   f'{" · ".join(anchors)}{tail}</div>')
    out.append('</div>')
    return out


def render_html(sections: dict[str, list[dict]], corner: tuple[list[dict], list[dict]],
                generated_on: date, window_days: int) -> str:
    wrap = ("font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
            "Helvetica,Arial,sans-serif;color:#0f172a;max-width:640px;"
            "margin:0 auto;padding:8px 4px;")
    out = [f'<div style="{wrap}">']
    out.append(f'<h1 style="font-size:20px;margin:0 0 2px;">State Activity Digest</h1>')
    out.append(f'<p style="color:#64748b;font-size:13px;margin:0 0 14px;">'
               f'Generated on {generated_on.strftime("%b %-d, %Y")} · '
               f'pulling from the last {window_days} days</p>')
    out.append(f'<p style="font-size:14px;color:#334155;line-height:1.5;margin:0 0 18px;">'
               f'{escape(INTRO)}</p>')

    for comp in COMPETENCIES:
        out.append(f'<h2 style="font-size:15px;border-bottom:2px solid #e2e8f0;'
                   f'padding-bottom:4px;margin:22px 0 10px;">'
                   f'{COMPETENCY_LABELS[comp]}</h2>')
        evs = sections[comp]
        if not evs:
            out.append('<p style="color:#94a3b8;font-size:13px;margin:0;">'
                       'Nothing notable last week.</p>')
            continue
        for e in evs:
            title = escape(re.sub(r"^[A-Z]{2} — ", "", e["name"]))
            first_url = e["source_urls"][0] if e["source_urls"] else ""
            title_html = (f'<a href="{escape(first_url)}" style="color:#0f172a;'
                          f'text-decoration:none;">{title}</a>' if first_url else title)
            dots = "●" * e["relevance"]
            out.append('<div style="margin:0 0 16px;">')
            out.append(f'<div style="font-weight:700;font-size:14px;">{title_html} '
                       f'<span style="color:#f59e0b;font-size:11px;">{dots}</span></div>')
            s = summary_of(e)
            if s:
                out.append(f'<div style="font-size:13px;color:#334155;line-height:1.5;'
                           f'margin:3px 0;">{escape(s)}</div>')
            ml = meta_line(e)
            if ml:
                out.append(f'<div style="font-size:12px;color:#64748b;">{escape(ml)}</div>')
            links = []
            for i, u in enumerate(e["source_urls"]):
                label = e["source_outlets"][i] if i < len(e["source_outlets"]) else u
                links.append(f'<a href="{escape(u)}" style="color:#2563eb;'
                             f'text-decoration:none;">{escape(label)}</a>')
            if links:
                out.append(f'<div style="font-size:12px;margin-top:2px;">'
                           f'{" · ".join(links)}</div>')
            out.append('</div>')

    # --- Gov Candidates Corner (foot of the digest) ---
    tier1, tier2 = corner
    out.append('<h2 style="font-size:15px;border-bottom:2px solid #e2e8f0;'
               'padding-bottom:4px;margin:28px 0 4px;">Gov Candidates Corner</h2>')
    out.append('<p style="color:#64748b;font-size:12px;margin:0 0 12px;">'
               "The 2026 governors&rsquo; races — what candidates are saying and "
               'doing on state capacity.</p>')
    if not tier1 and not tier2:
        out.append('<p style="color:#94a3b8;font-size:13px;margin:0;">'
                   'Nothing notable from the 2026 races last week.</p>')
    else:
        for d in tier1:
            out += render_dev_html(d)
        if tier2:
            out.append('<div style="font-size:12px;font-weight:700;color:#64748b;'
                       'text-transform:uppercase;letter-spacing:.03em;margin:6px 0 10px;">'
                       'Also notable elsewhere</div>')
            for d in tier2:
                out += render_dev_html(d)

    out.append(f'<p style="border-top:1px solid #e2e8f0;margin-top:24px;'
               f'padding-top:12px;font-size:13px;">'
               f'<a href="{escape(TRACKER_URL)}" style="color:#2563eb;'
               f'text-decoration:none;font-weight:600;">See the full tracker →</a></p>')
    out.append('</div>')
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Sending (§6)
# --------------------------------------------------------------------------- #

def get_recipients(override: str | None) -> list[str]:
    """The only thing a subscriber model changes later. §0: keep RECIPIENTS as-is."""
    if override:
        return [override]
    return RECIPIENTS


def send_email(subject: str, html: str, text: str, recipients: list[str]) -> None:
    if not RESEND_API_KEY:
        sys.exit("Missing RESEND_API_KEY; see digest_feature_brief.md §6.")
    payload = {
        "from": DIGEST_FROM,
        "to": recipients,
        "subject": subject,
        "html": html,
        "text": text,
    }
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                 "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    if not (200 <= resp.status_code < 300):
        # §0/§6: surface the full Resend error (a 403 here usually means the
        # recipient isn't the Resend account address pre-DNS-verification).
        raise RuntimeError(
            f"Resend send failed: HTTP {resp.status_code} — {resp.text}"
        )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(description="Send the weekly state-capacity email digest.")
    ap.add_argument("--days", type=int, default=7, help="Digest window (default 7).")
    ap.add_argument("--since", default=None, metavar="YYYY-MM-DD",
                    help="Anchor the window to this date (e.g. last Monday) instead "
                         "of --days back; also sets the 'week of' header label.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Render + per-category counts to stdout; send nothing.")
    ap.add_argument("--to", default=None, help="Override recipient (post-DNS only).")
    args = ap.parse_args()

    events = load_events(args.days, args.since)
    sections = select_all(events)
    total = len({e["name"] for evs in sections.values() for e in evs})

    generated_on = date.today()
    cutoff = window_cutoff(args.days, args.since)
    window_days = (generated_on - date.fromisoformat(cutoff)).days
    subject = SUBJECT

    devs = load_candidate_devs(args.days, args.since)
    corner = select_candidate_corner(devs, load_roster())

    html = render_html(sections, corner, generated_on, window_days)
    text = render_text(sections, corner, generated_on, window_days)

    if args.dry_run:
        print(f"Window: since {cutoff} ({window_days} days) · {len(events)} events in window")
        print(f"Subject: {subject}\n")
        for comp in COMPETENCIES:
            evs = sections[comp]
            n3 = sum(1 for e in evs if e["relevance"] == 3)
            n2 = sum(1 for e in evs if e["relevance"] == 2)
            print(f"[{COMPETENCY_LABELS[comp]}] {len(evs)} selected ({n3}×●●● + {n2}×●●)")
            for e in evs:
                title = re.sub(r"^[A-Z]{2} — ", "", e["name"])
                print(f"    {'●' * e['relevance']:<3} {e['state']:<3} {title}")
            if not evs:
                print("    (nothing notable last week)")
            print()
        tier1, tier2 = corner
        print(f"[Gov Candidates Corner] {len(devs)} RAF-relevant devs in window · "
              f"{len(tier1)} priority (open/competitive, ≥2) + {len(tier2)} other (=3)")
        for lbl, group in (("priority", tier1), ("other", tier2)):
            for d in group:
                print(f"    {'●' * d['relevance']:<3} {d['state']:<3} "
                      f"{d['candidate']:<20} {d['_rating'] or '—':<8} {d['headline'][:52]}")
        if not tier1 and not tier2:
            print("    (nothing notable from the 2026 races last week)")
        print("\n--- dry run: no email sent ---")
        return

    recipients = get_recipients(args.to)
    send_email(subject, html, text, recipients)
    print(f"Sent digest ({total} events) to {', '.join(recipients)} from {DIGEST_FROM}")


if __name__ == "__main__":
    main()
