#!/usr/bin/env python3
"""Thin Congress.gov API client.

Docs: https://api.congress.gov. Key comes from CONGRESS_API_KEY.

Rate limit is 20,000 requests/hour — far beyond what this pipeline needs, so
there's no backoff logic. `remaining()` surfaces the header anyway so a future
problem shows up in the logs instead of as mysterious empty results.
"""

import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("CONGRESS_API_KEY")
BASE = "https://api.congress.gov/v3"
TIMEOUT = 30
DELAY = 0.1

# The 119th Congress runs Jan 2025 - Jan 2027.
CURRENT_CONGRESS = 119

_last_remaining = None


class MissingKey(RuntimeError):
    pass


def have_key():
    return bool(API_KEY)


def remaining():
    return _last_remaining


def get(path, **params):
    """GET /v3/{path}. Raises MissingKey if the key isn't configured, so
    callers can degrade to a clean skip rather than a stack trace."""
    global _last_remaining
    if not API_KEY:
        raise MissingKey(
            "CONGRESS_API_KEY is not set. Add it to .env (local) and to the "
            "repo's GitHub Actions secrets (CI). Get one at https://api.congress.gov."
        )
    params = {k: v for k, v in params.items() if v is not None}
    params.update({"api_key": API_KEY, "format": "json"})
    r = requests.get(f"{BASE}/{path.lstrip('/')}", params=params, timeout=TIMEOUT)
    _last_remaining = r.headers.get("x-ratelimit-remaining")
    if r.status_code != 200:
        raise RuntimeError(f"congress.gov {r.status_code} on /{path}: {r.text[:200]}")
    return r.json()


def paginate(path, key, limit=250, max_items=5000, nested=None, **params):
    """Walk a list endpoint via offset. `key` is the list property in the
    response body (e.g. 'committeeMeetings').

    `nested` handles /committee/*/bills, which wraps its list one level deeper
    as {"committee-bills": {"bills": [...]}} rather than returning a bare list.
    Without unwrapping, extending a list with that dict silently yields its
    keys — three per page, for every committee.
    """
    out, offset = [], 0
    while len(out) < max_items:
        data = get(path, limit=limit, offset=offset, **params)
        batch = data.get(key) or []
        if nested and isinstance(batch, dict):
            batch = batch.get(nested) or []
        if not batch:
            break
        out.extend(batch)
        total = (data.get("pagination") or {}).get("count")
        offset += len(batch)
        if total is not None and offset >= total:
            break
        if len(batch) < limit:
            break
        time.sleep(DELAY)
    return out[:max_items]


def iso(d):
    """A date -> the ISO-Z timestamp the API's fromDateTime expects."""
    return f"{d.isoformat()}T00:00:00Z"


# --- meetings -------------------------------------------------------------
def list_meetings(chamber, since, congress=CURRENT_CONGRESS):
    """Meetings updated since `since`. The list carries only eventId +
    updateDate — the committee isn't known until the detail fetch."""
    return paginate(f"committee-meeting/{congress}/{chamber}", "committeeMeetings",
                    fromDateTime=iso(since))


def get_meeting(chamber, event_id, congress=CURRENT_CONGRESS):
    return get(f"committee-meeting/{congress}/{chamber}/{event_id}").get("committeeMeeting", {})


# --- bills ----------------------------------------------------------------
def list_committee_bills(chamber, system_code, since):
    """Bills referred to / reported by one committee, updated since `since`.
    Far tighter than /v3/bill: HSGAC returns ~89 for a 21-day window against
    ~3,600 for an unscoped query over the same period."""
    return paginate(f"committee/{chamber}/{system_code}/bills", "committee-bills",
                    nested="bills", fromDateTime=iso(since))


def get_bill(congress, bill_type, number):
    return get(f"bill/{congress}/{bill_type.lower()}/{number}").get("bill", {})


def get_bill_summary(congress, bill_type, number):
    """Latest CRS summary, or "" — often absent even for live bills, so
    callers must not depend on it."""
    try:
        data = get(f"bill/{congress}/{bill_type.lower()}/{number}/summaries")
    except RuntimeError:
        return ""
    summaries = data.get("summaries") or []
    if not summaries:
        return ""
    import re
    return re.sub(r"<[^>]+>", " ", summaries[-1].get("text", "")).strip()


if __name__ == "__main__":
    from datetime import date, timedelta
    from tracker.congress import sources as congress_sources

    if not have_key():
        raise SystemExit("CONGRESS_API_KEY not set")
    since = date.today() - timedelta(days=21)
    for chamber in ("senate", "house"):
        ms = list_meetings(chamber, since)
        print(f"{chamber}: {len(ms)} meetings updated since {since}")
    for key, c in congress_sources.COMMITTEES.items():
        bills = list_committee_bills(c["chamber"], c["code"], since)
        print(f"{key:16} {c['code']}  bills={len(bills)}")
    print("rate limit remaining:", remaining())
