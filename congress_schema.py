#!/usr/bin/env python3
"""Enums and Airtable field definitions for the congressional tables.

The state pipeline redeclares its choice lists in every script that touches
them (PILLAR_CHOICES lives in five files, TOPIC_TAG_CHOICES in four). This
module is the single declaration for the congress side — import from here.

Four tables:
    Congress Raw       one scraped press item      append, URL-deduped
    Congress Events    one deduped activity event  upsert on event_id
    Congress Hearings  one hearing                 upsert on hearing_key
    Congress Bills     one bill                    upsert on bill_id
"""

RAW_TABLE = "Congress Raw"
EVENTS_TABLE = "Congress Events"
HEARINGS_TABLE = "Congress Hearings"
BILLS_TABLE = "Congress Bills"

# Unchanged from rubric.md — same four, same colors in the web UI. The
# congressional adaptation re-points them at the federal government rather
# than adding a fifth.
COMPETENCY_CHOICES = ["civil-service", "procedure", "digital", "incentives"]

# The state tracker's 26, plus six congressional additions. Kept as one list so
# a tag means the same thing on both tabs.
TOPIC_TAG_CHOICES = [
    "it-modernization", "ai", "data-privacy", "cybersecurity", "broadband",
    "benefits-systems", "procurement", "occupational-licensing", "permitting",
    "housing-land-use", "regulatory-reform", "hiring-recruitment",
    "compensation-pensions", "labor-relations", "telework-rto", "layoffs-rif",
    "reorganization", "transparency", "study-commission",
    "data-center", "tax-incentives", "energy-utility", "health-human-services",
    "higher-ed", "k12-education", "child-welfare",
    # congressional additions
    "elections-admin", "federal-workforce", "appropriations", "nominations",
    "oversight-investigation", "shutdown-cr",
]

CHAMBER_CHOICES = ["senate", "house", "joint", "n/a"]

COMMITTEE_CHOICES = [
    "hsgac", "senate-rules", "senate-approps", "house-oversight",
    "house-admin", "house-rules", "house-approps", "leadership", "gao", "cbo",
]

PARTY_CHOICES = ["majority", "minority", "member", "nonpartisan"]

ACTIVITY_TYPE_CHOICES = [
    "hearing-notice", "hearing-held", "markup", "bill-introduced",
    "bill-reported", "bill-passed-chamber", "bill-enacted", "oversight-letter",
    "subpoena", "report-released", "nomination", "approps-action",
    "rule-adopted", "statement",
]

SOURCE_KIND_CHOICES = ["wp_api", "rss", "html", "congress-api"]

HEARING_STATUS_CHOICES = ["scheduled", "held", "postponed", "canceled"]

BILL_STATUS_CHOICES = [
    "introduced", "in-committee", "reported", "passed-chamber",
    "passed-both", "enacted", "vetoed", "failed",
]

# What the committee did with the bill, from the relationshipType on
# /committee/*/bills. This is *why* a bill is in the list at all — the
# endpoint returns bills whose record changed in the window, and this says
# what changed. HSGAC's last 21 days: 56 marked up, 31 referred, 2 reported.
COMMITTEE_ACTION_CHOICES = ["marked-up", "reported", "referred", "other"]

# Human review lives in Airtable. `unreviewed` is the default; the upsert path
# in airtable_util preserves these two fields so a nightly run never clobbers
# what a reviewer typed.
REVIEW_STATUS_CHOICES = ["unreviewed", "approved", "rejected", "needs-edit"]
REVIEW_FIELDS = ("review_status", "reviewer_notes")


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

_CLASSIFICATION = [
    _sel("competency", COMPETENCY_CHOICES, multi=True),
    _num("relevance"),
    _sel("topic_tags", TOPIC_TAG_CHOICES, multi=True),
]

RAW_FIELDS = [
    {"name": "Name", "type": "singleLineText"},
    _text("headline", multi=True),
    _text("notes", multi=True),
    _date("date"),
    _sel("committee", COMMITTEE_CHOICES),
    _sel("chamber", CHAMBER_CHOICES),
    _sel("party_source", PARTY_CHOICES),
    _sel("activity_type", ACTIVITY_TYPE_CHOICES),
    _sel("pillars", COMPETENCY_CHOICES, multi=True),
    _text("actor"),
    _text("source"),
    _sel("source_kind", SOURCE_KIND_CHOICES),
    _text("source_urls", multi=True),
    _text("bill_refs"),
    _text("status"),
    # The state pipeline has no ingestion timestamp, so dedupe.py windows on
    # `date` — which the classifier fills with the date of the action. An item
    # published today about something from six weeks ago then falls outside
    # every future window and is lost. congress_dedupe.py windows on this
    # field instead.
    _datetime("ingested_at"),
]

EVENT_FIELDS = [
    {"name": "Name", "type": "singleLineText"},
    _text("event_id"),
    # The 5-10 word action title the cluster step already produces. Kept
    # separate from the `Name` primary field (which is prefixed with the
    # committee) so the UI can lead with a short bold title and put the
    # full-sentence `headline` behind an expander.
    _text("short_title"),
    _text("headline", multi=True),
    _text("summary", multi=True),
    _text("why_it_matters", multi=True),
    _date("date"),
    _sel("committee", COMMITTEE_CHOICES),
    _sel("chamber", CHAMBER_CHOICES),
    _sel("party_source", PARTY_CHOICES),
    _sel("activity_type", ACTIVITY_TYPE_CHOICES),
    *_CLASSIFICATION,
    _text("actor"),
    _text("bill_refs"),
    _text("status"),
    _text("source_urls", multi=True),
    _text("source_outlets", multi=True),
    _num("article_count"),
    *_REVIEW,
    _datetime("deduped_at"),
]

HEARING_FIELDS = [
    {"name": "Name", "type": "singleLineText"},
    _text("hearing_key"),
    # Congress.gov's "title" for a hearing is the full agenda — a markup can
    # run 1,500+ characters listing every bill. Truncating it still reads
    # badly, so the classifier writes a real title and `title` keeps the raw
    # agenda for the expanded view.
    _text("short_title"),
    _text("title", multi=True),
    _text("agenda_summary", multi=True),
    _text("why_it_matters", multi=True),
    _datetime("hearing_date"),
    _date("date"),
    _sel("committee", COMMITTEE_CHOICES),
    _sel("chamber", CHAMBER_CHOICES),
    _text("location"),
    _text("witnesses", multi=True),
    _text("materials_urls", multi=True),
    _text("bill_refs"),
    _text("meeting_type"),
    _sel("hearing_status", HEARING_STATUS_CHOICES),
    *_CLASSIFICATION,
    _text("source_urls", multi=True),
    *_REVIEW,
    _datetime("synced_at"),
]

BILL_FIELDS = [
    {"name": "Name", "type": "singleLineText"},
    _text("bill_id"),
    _text("bill_number"),
    _num("congress"),
    _text("title", multi=True),
    _text("summary", multi=True),
    # CRS's own summary, when Congress.gov has one. Coverage is inverted from
    # what's useful: roughly half of all bills have one, but only 3 of 26
    # high-relevance bills did on the first backfill — CRS lags, and the
    # bills that are already summarized are mostly post-office namings. So
    # this supplements our generated summary rather than replacing it.
    _text("crs_summary", multi=True),
    _text("why_it_matters", multi=True),
    _date("date"),
    _date("introduced_date"),
    _sel("committee", COMMITTEE_CHOICES),
    _sel("chamber", CHAMBER_CHOICES),
    # What the committee did, and when — this is what puts the bill in the
    # window. `date` mirrors committee_action_date so the UI's time filter
    # means "the committee acted on this recently" rather than "the bill's
    # latest floor action was recent", which can be a year older.
    _sel("committee_action", COMMITTEE_ACTION_CHOICES),
    _date("committee_action_date"),
    _text("sponsor"),
    _text("sponsor_party"),
    _num("cosponsor_count"),
    _text("latest_action", multi=True),
    _date("latest_action_date"),
    _sel("bill_status", BILL_STATUS_CHOICES),
    _text("policy_area"),
    *_CLASSIFICATION,
    _text("source_urls", multi=True),
    *_REVIEW,
    _datetime("synced_at"),
]


def valid(values, choices):
    """Drop anything the Airtable select doesn't know about. typecast=True
    would otherwise invent new choices from a model typo."""
    return [v for v in (values or []) if v in choices]


def clamp_relevance(value):
    try:
        r = int(value)
    except (TypeError, ValueError):
        return None
    return r if 1 <= r <= 3 else None
