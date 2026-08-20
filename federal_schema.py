#!/usr/bin/env python3
"""Enums and Airtable field definitions for the federal (executive-branch) tables.

Same contract as congress_schema.py: one declaration, imported everywhere, so a
choice list never drifts between the pipeline, the dedupe pass and the web view.

Two tables:
    Federal Raw       one scraped item (article / release / FR doc)  append, URL-deduped
    Federal Events    one deduped federal action                     upsert on event_id

The four competencies and the topic-tag vocabulary are imported from
congress_schema rather than re-declared: a tag has to mean the same thing on the
Congress tab and this one, or the two tabs stop being comparable.
"""

from congress_schema import (  # noqa: F401  (re-exported on purpose)
    COMPETENCY_CHOICES,
    REVIEW_FIELDS,
    REVIEW_STATUS_CHOICES,
    clamp_relevance,
    valid,
)
from congress_schema import TOPIC_TAG_CHOICES as _CONGRESS_TAGS

RAW_TABLE = "Federal Raw"
EVENTS_TABLE = "Federal Events"

# Six additions on top of the shared 32. Everything else the executive branch
# does already has a tag: RIFs are `layoffs-rif`, reorgs are `reorganization`,
# telework is `telework-rto`, IT is `it-modernization`.
FEDERAL_TAGS = [
    "acquisition-far",      # FAR rewrites, contract vehicles, category management
    "grants-management",    # uniform guidance, grant administration burden
    "paperwork-burden",     # PRA, information collections, reporting mandates
    "improper-payments",    # payment integrity, fraud controls
    "customer-experience",  # service delivery, CX executive actions, Login.gov
    "merit-system",         # Schedule F / merit protections / MSPB & FLRA
]
TOPIC_TAG_CHOICES = _CONGRESS_TAGS + FEDERAL_TAGS

# ---------------------------------------------------------------------------
# Lane — which of the four sections of the tab an item belongs to. This is
# assigned by the SOURCE, never by the model: a FedScoop story about an OMB
# memo is news about an executive action, and conflating the two would let
# trade-press coverage masquerade as a primary-source instrument.
# ---------------------------------------------------------------------------
LANE_CHOICES = ["executive-action", "oversight", "news", "rulemaking"]

# Branch of government the underlying action belongs to. The Hill covers all
# three; this is what lets the federal tab show a "congress" chip and stay
# legible next to the Congress tab, which is committee-sourced instead.
BRANCH_CHOICES = ["executive", "congress", "judiciary", "multi"]

# ---------------------------------------------------------------------------
# Agencies. Multi-select: the agency or agencies the action is BY or ABOUT.
# The four we scrape directly lead the list; the rest exist so a reader can
# filter "everything touching VA benefits systems" out of the news lane.
# `governmentwide` is for actions that bind every agency (most OMB memos);
# `other` is the escape hatch so the model never has to invent a choice.
# ---------------------------------------------------------------------------
AGENCY_CHOICES = [
    "opm", "omb", "gsa", "white-house",
    "governmentwide",
    "gao", "mspb", "flra", "oge", "nara", "oira",
    "dod", "va", "ssa", "hhs", "cms", "irs", "treasury",
    "dhs", "cisa", "fema", "tsa", "cbp-ice",
    "state", "doj", "ed", "dol", "doi", "usda", "doe", "epa", "hud",
    "dot", "faa", "sba", "nasa", "nsf", "commerce", "nist", "census",
    "eac", "fcc", "ftc", "sec", "nrc", "usaid", "usps",
    "courts", "other",
]

# ---------------------------------------------------------------------------
# Instrument type — the answer to "what is the actual thing that happened?"
# This is the spine of the gate: an item that cannot be assigned one of these
# is rhetoric, and rhetoric does not enter the table. See
# federal_rubric_adaptation.md for the instrument test.
# ---------------------------------------------------------------------------
INSTRUMENT_TYPE_CHOICES = [
    "omb-memo",              # M-26-15 and friends
    "omb-circular",          # A-11, A-130, A-123 revisions
    "agency-guidance",       # OPM governmentwide guidance, GSA policy letters
    "executive-order",
    "presidential-memo",
    "regulation-proposed",
    "regulation-final",
    "federal-register-notice",
    "directive-order",       # an order or directive to agencies short of a rule
    "policy-launch",         # a new program, initiative or authority in effect
    "system-launch",         # a system, platform or service going live
    "workforce-action",      # RIF, hiring authority, reclassification, pay action
    "procurement-action",    # solicitation, contract vehicle, acquisition change
    "reorganization",        # agency stood up, merged, moved or abolished
    "report-findings",       # a report that examined something and found it
    "ig-audit",
    "court-order",           # a court ordering an agency to do or stop something
    "data-release",
    "news-report",           # trade press reporting an action; see `verification`
]

# How well established the action is. Trade press reporting a draft memo before
# it is signed is real signal in this space — dropping it would lose most of
# what FedScoop and GovExec are useful for — so it is kept and labelled instead.
VERIFICATION_CHOICES = ["official", "reported", "draft-leaked"]

SOURCE_KIND_CHOICES = ["wp_api", "rss", "html", "fedreg-api"]


def _sel(name, choices, multi=False):
    return {
        "name": name,
        "type": "multipleSelects" if multi else "singleSelect",
        "options": {"choices": [{"name": c} for c in choices]},
    }


def _text(name, multi=False):
    return {"name": name, "type": "multilineText" if multi else "singleLineText"}


def _num(name):
    return {"name": name, "type": "number", "options": {"precision": 0}}


def _date(name):
    return {"name": name, "type": "date", "options": {"dateFormat": {"name": "iso"}}}


def _datetime(name):
    return {"name": name, "type": "dateTime",
            "options": {"dateFormat": {"name": "iso"},
                        "timeFormat": {"name": "24hour"},
                        "timeZone": "utc"}}


_REVIEW = [_sel("review_status", REVIEW_STATUS_CHOICES), _text("reviewer_notes", multi=True)]

_INSTRUMENT = [
    _sel("instrument_type", INSTRUMENT_TYPE_CHOICES),
    # "M-26-15", "EO 14170", "90 FR 33421", "GAO-26-107". Free text because the
    # numbering conventions are per-instrument and we want the string verbatim.
    _text("instrument_id"),
    _sel("verification", VERIFICATION_CHOICES),
]

RAW_FIELDS = [
    {"name": "Name", "type": "singleLineText"},
    _text("headline", multi=True),
    _text("notes", multi=True),
    _date("date"),
    _sel("lane", LANE_CHOICES),
    _sel("branch", BRANCH_CHOICES),
    _sel("agency", AGENCY_CHOICES, multi=True),
    *_INSTRUMENT,
    _sel("pillars", COMPETENCY_CHOICES, multi=True),
    _text("actor"),
    _text("source"),
    _sel("source_kind", SOURCE_KIND_CHOICES),
    _text("source_urls", multi=True),
    # The primary-source document the item points at, when the item is not
    # itself that document: the PDF an OPM release announces, the FR page a
    # news story is about. This is what a reviewer clicks to check the framing.
    _text("document_url"),
    _text("status"),
    _datetime("ingested_at"),
]

EVENT_FIELDS = [
    {"name": "Name", "type": "singleLineText"},
    _text("event_id"),
    _text("short_title"),
    _text("headline", multi=True),
    _text("summary", multi=True),
    _text("why_it_matters", multi=True),
    _date("date"),
    _sel("lane", LANE_CHOICES),
    _sel("branch", BRANCH_CHOICES),
    _sel("agency", AGENCY_CHOICES, multi=True),
    *_INSTRUMENT,
    _sel("competency", COMPETENCY_CHOICES, multi=True),
    _num("relevance"),
    _sel("topic_tags", TOPIC_TAG_CHOICES, multi=True),
    _text("actor"),
    _text("status"),
    _text("document_url"),
    _text("source_urls", multi=True),
    _text("source_outlets", multi=True),
    _num("article_count"),
    *_REVIEW,
    _datetime("deduped_at"),
]
