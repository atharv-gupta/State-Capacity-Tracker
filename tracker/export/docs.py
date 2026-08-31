#!/usr/bin/env python3
"""Generate the reviewer-facing walkthrough documents for both federal trackers.

Two documents — one for Congress, one for the federal executive branch — each
with a plain-language description of how an item becomes a row, followed by
appendices carrying every prompt, keyword list and enum VERBATIM.

The point of generating rather than writing these: the appendices are read out of
the running code at build time, so a prompt edit can never leave the document
describing a pipeline that no longer exists. Regenerate before each send.

    python export_docs.py                      # markdown + docx into review/
    python export_docs.py --format md          # markdown only
    python export_docs.py --out ~/Desktop

Requires pandoc for .docx output (brew install pandoc); markdown always works.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import date

from dotenv import load_dotenv

from tracker.congress import api_sync as congress_api_sync
from tracker.congress import dedupe as congress_dedupe
from tracker.congress import llm as congress_llm
from tracker.congress import pipeline as congress_pipeline
from tracker.congress import schema as congress_schema
from tracker.congress import sources as congress_sources
from tracker.federal import dedupe as federal_dedupe
from tracker.federal import llm as federal_llm
from tracker.federal import pipeline as federal_pipeline
from tracker.federal import schema as federal_schema
from tracker.federal import sources as federal_sources

load_dotenv()

FENCE = "~" * 6          # long enough that nothing inside a prompt closes it


def verbatim(text):
    return f"{FENCE}\n{text.strip()}\n{FENCE}\n"


def demote(md, levels=2):
    """Push every ATX heading in an embedded markdown document down N levels, so
    the rubric's own `##` headings nest under the appendix that contains them
    instead of competing with the document's structure."""
    return re.sub(r"^(#{1,4}) ", lambda m: "#" * (len(m.group(1)) + levels) + " ",
                  md, flags=re.MULTILINE)


def task_suffix(full, rubric_system):
    """The output instruction a script appends after the shared rubric. Printing
    only the difference keeps the rubric from appearing twice in one document."""
    return full.replace(rubric_system, "").strip()


def keyword_block(mapping):
    out = []
    for pillar, words in mapping.items():
        out.append(f"{pillar}  ({len(words)} patterns)")
        out.append("  " + "\n  ".join(", ".join(words[i:i + 4]) for i in range(0, len(words), 4)))
        out.append("")
    return verbatim("\n".join(out))


def airtable_counts(tables):
    """Live row counts, so the document says what the tables actually hold.
    Falls back to a dash rather than failing the build."""
    try:
        from pyairtable import Api
        api = Api(os.environ["AIRTABLE_TOKEN"])
        base = api.base(os.environ["AIRTABLE_BASE_ID"])
        return {t: len(base.table(t).all()) for t in tables}
    except Exception as e:
        print(f"  (Airtable counts unavailable: {e})")
        return {t: "—" for t in tables}


HEADER_NOTE = (
    "*Generated {today} from the running pipeline. Everything in the appendices is read "
    "out of the live code at build time — not retyped — so it is exactly what the models "
    "see. Regenerate with `python export_docs.py`.*"
)

ASK = """## What we need from you

Three questions, in order of how much they matter:

1. **Did we drop something we shouldn't have?** This is the expensive kind of error and
   the one you are best placed to catch, because you know what matters and the pipeline
   only knows what it was told. The raw sheet in the accompanying spreadsheet shows what
   survived the first filter; if something you would expect to see is missing entirely,
   that is a keyword or a prompt problem and we want to know.
2. **Is anything here not really an action?** A press release that announces nothing, a
   report that examines nothing, a statement about someone else's statement.
3. **Are the competency and relevance calls right?** Zero competencies is the common and
   correct answer — most government activity is not about the government's own capacity.
   Direction is irrelevant: dismantling a capacity counts exactly as much as building one.

Mark up the spreadsheet, not this document — it has a verdict column with a dropdown.
Rows you don't touch are read as "no opinion", not as "keep".
"""


# ---------------------------------------------------------------------------
# Congress
# ---------------------------------------------------------------------------
def congress_doc():
    counts = airtable_counts(["Congress Raw", "Congress Events",
                              "Congress Hearings", "Congress Bills"])
    n_sources = congress_sources.source_count()
    n_kw = sum(len(v) for v in congress_pipeline.PILLAR_KEYWORDS.values())

    src_rows = "\n".join(
        f"| {s['name']} | {congress_sources.COMMITTEES.get(s['committee'], {}).get('name') or congress_sources.EXTRA_COMMITTEES.get(s['committee'], {}).get('name') or s['committee']} | "
        f"{ {'wp_api': 'WordPress API', 'rss': 'RSS', 'html': 'scraped page'}[k] } |"
        for k, s in congress_sources.all_congress_sources())

    cs_ = congress_schema
    tags = "\n  ".join(", ".join(cs_.TOPIC_TAG_CHOICES[i:i + 6])
                       for i in range(0, len(cs_.TOPIC_TAG_CHOICES), 6))
    enums = "\n".join([
        f"competency:      {' | '.join(cs_.COMPETENCY_CHOICES)}",
        "relevance:       1 | 2 | 3   (blank when no competency)",
        f"activity_type:   {' | '.join(cs_.ACTIVITY_TYPE_CHOICES)}",
        f"committee:       {' | '.join(cs_.COMMITTEE_CHOICES)}",
        f"chamber:         {' | '.join(cs_.CHAMBER_CHOICES)}",
        f"party_source:    {' | '.join(cs_.PARTY_CHOICES)}",
        f"hearing_status:  {' | '.join(cs_.HEARING_STATUS_CHOICES)}",
        f"bill_status:     {' | '.join(cs_.BILL_STATUS_CHOICES)}",
        f"review_status:   {' | '.join(cs_.REVIEW_STATUS_CHOICES)}",
        "",
        "topic_tags:",
        "  " + tags,
    ])
    enum_block = verbatim(enums)

    cmte_rows = "\n".join(
        f"| {c['name']} | {c['chair']} | {c['ranking']} |"
        for c in congress_sources.COMMITTEES.values())

    return f"""# Congressional tracker — how an item becomes a row

{HEADER_NOTE.format(today=date.today().isoformat())}

## What this tracker is

A daily feed of what Congress is doing about **how the federal government runs itself** —
not what it regulates in the economy. Coverage is scoped to the {len(congress_sources.COMMITTEES)}
committees with jurisdiction over government operations, plus both party whips and CBO.

Everything is scored against the same four Recoding America competencies used on the state
tracker, re-pointed at the federal government:

- **civil-service** — how the federal government hires, classifies, pays, evaluates, and
  separates its own employees, and where that authority sits.
- **procedure** — the federal government's own procedural and compliance burden.
- **digital** — how the federal government builds, buys, staffs and oversees its own
  technology and data.
- **incentives** — the federal learning loop: oversight, evaluation, whether anyone checks
  if a program works.

State impact is **not** a criterion. An action that stays entirely inside the federal
government is fully in scope.

**GAO is no longer here.** It moved to the federal executive-branch tracker on 2026-08-20,
because its reports were arriving on both tabs with nothing to deduplicate them. See that
document instead. CBO remains.

Current contents: **{counts['Congress Events']} events**, {counts['Congress Hearings']} hearings,
{counts['Congress Bills']} bills, from {counts['Congress Raw']} raw press items.

{ASK}

## The flow, in plain language

There are two independent paths, because they need different handling.

```
PRESS PATH ({n_sources} sources)
  everything published  ->  filter 1: keywords  ->  filter 2: AI gate  ->  raw table
                                                          |
                                    filter 3: AI clustering + classification
                                                          |
                                                     events table

API PATH (Congress.gov)
  committee meetings + committee bills  ->  filter 1: policy area  ->  AI classification
                                                          |
                                              hearings and bills tables
```

### Press path, stage 0 — the sources

{n_sources} feeds: the seven committees' own press pages, their chairs' and ranking members'
offices, both party whips, and CBO. Three technical kinds — a WordPress API where one exists
(full article text), RSS where it works, and a scraped listing page where neither does.
Appendix A lists every one.

Two things worth knowing. First, **these offices publish mostly messaging**: reaction
statements, praise, criticism, ICYMI roundups. Filtering that out is most of the job. Second,
**silence is usually the calendar, not a bug** — during recess most of these feeds go quiet
for weeks, and the pipeline prints a per-source count on every run so we can tell a quiet
committee from a broken scraper.

### Stage 1 — the keyword pre-screen (no AI, costs nothing)

Every item's title and body are matched against {n_kw} regular-expression patterns grouped by
competency — "Schedule F", "reduction in force", "FedRAMP", "improper payments", and so on.
An item matching none of them is dropped before any AI runs.

This is the **cheapest and riskiest** step in the pipeline. Cheap because it removes most of
the volume for free. Risky because a real action described in words nobody thought to add to
the list is invisible from here on. **If something is missing from the spreadsheet entirely,
this is the most likely reason** — and the fix is a word, not a model. Appendix B is the
complete list.

### Stage 2 — the gate (Claude Haiku, a small fast model)

Each survivor gets two questions:

**Is there an action?** A hearing scheduled or held, a markup, a bill introduced or reported,
an oversight letter sent, a subpoena issued, a report released, a nomination advanced, a
committee rule adopted. Reaction statements, floor speeches with no underlying action,
"X slams Y", ICYMI roundups, district events and ceremonial items all fail. A press release
*about* a real action passes — the action is the event even when the framing is partisan.

**Does it touch a competency?** One of the four above, judged on the government's own
machinery rather than the subject matter.

Most items fail, and that is correct. Survivors are written to the raw table, one row per
item. Appendix C is the prompt, verbatim.

### Stage 3 — clustering (Claude Sonnet, a larger model)

One action reaches us many times: a majority office, a minority office and three members'
offices all write up the same markup. This step groups rows describing the same underlying
action into a single **event** and synthesizes a neutral account of it, keeping every source
URL. Rows are grouped by chamber rather than by committee, because members sit on several
committees and letters are usually joint.

Appendix D is the prompt.

### Stage 4 — classification (Claude Sonnet, against the full rubric)

Every event — not just the promising ones — is classified against the complete rubric:
zero, one or more competencies, a 1–3 relevance score for how central an example it is, and
descriptive topic tags. This pass is authoritative; it regularly overrules the stage-2 gate,
which is why the raw sheet and the events sheet in the spreadsheet disagree.

The rubric is the state tracker's rubric with a congressional adaptation prepended.
Appendix E is both documents in full, exactly as the model receives them.

### The API path — hearings and bills

Hearings and bills come from the Congress.gov API rather than scraping, so they arrive with
room, agenda, witness documents and bill linkage attached. **No clustering is needed** — one
API record is one hearing or one bill, with a stable ID.

The cheap first filter here is Congress.gov's own `policyArea` field rather than keywords:
bills outside {len(congress_api_sync.CAPACITY_POLICY_AREAS)} policy areas
({', '.join(sorted(congress_api_sync.CAPACITY_POLICY_AREAS))}) skip the AI entirely. It is
kept deliberately generous — the rubric does the real filtering. Appendix F is that prompt.

Expect the bills sheet to be mostly `none`: it contains everything the tracked committees
acted on, and most bills referred to a committee are narrow or commemorative.

## Known weaknesses — the things to look for

- **The keyword list bounds everything.** Stage 1 is a list of words a person wrote. Misses
  come from there far more often than from the models.
- **Committee attribution is by feed, not jurisdiction.** An item is filed under the
  committee whose feed carried it. A member sits on several.
- **Items are dated by the action, not by publication.** A release this week about something
  from May is dated May, which can push it outside a 30-day view.
- **Recess makes everything look broken.** In one August window, 9 of 28 sources returned
  nothing; all 9 were verified quiet, not failing. Senate Rules' majority page has published
  nothing since February.
- **Appropriations are `none` by default.** A funding level is not a capacity event. It
  counts only when the funding *model* changes — multi-year authority, reprogramming
  flexibility, outcome-contingency. If you think that rule is wrong, say so; it is a
  judgement call we made, not a fact.

---

# Appendix A — Source registry ({n_sources})

| Source | Committee / body | How we read it |
|---|---|---|
{src_rows}

## Committees tracked

| Committee | Chair | Ranking member |
|---|---|---|
{cmte_rows}

---

# Appendix B — Keyword pre-screen, verbatim

Python regular expressions, matched case-insensitively against title + body. `\\b` marks a
word boundary; `\\w*` allows any word ending.

{keyword_block(congress_pipeline.PILLAR_KEYWORDS)}

---

# Appendix C — Stage 2 gate prompt, verbatim

Model: `{congress_llm.MODEL_GATE}`. Sent as the system prompt; the item's title, body,
source and date are sent as the user message.

{verbatim(congress_pipeline.SYSTEM_PROMPT)}

---

# Appendix D — Stage 3 clustering prompt, verbatim

Model: `{congress_llm.MODEL_CLASSIFY}`.

{verbatim(congress_dedupe.CLUSTER_SYSTEM)}

---

# Appendix E — The classification rubric, in full

Model: `{congress_llm.MODEL_CLASSIFY}`. This is the entire text the classifier receives: the
congressional adaptation first, then the shared rubric, concatenated exactly as reproduced
here. It is shown with its original formatting rather than as a code block because this is the
document to argue with — if a rule here is wrong, everything downstream of it is wrong.

The same rubric is used for press events, for hearings and for bills; only the output
instruction at the end differs, and both variants are given below.

{demote(congress_llm.ADAPTATION)}

{demote(congress_llm.RUBRIC)}

## E.1 — Output instruction for press events

Appended after the rubric above by `congress_dedupe.py`.

{verbatim(task_suffix(congress_dedupe.CLASSIFY_SYSTEM, congress_llm.RUBRIC_SYSTEM))}

## E.2 — Output instruction for hearings and bills

Appended after the same rubric by `congress_api_sync.py`.

{verbatim(task_suffix(congress_api_sync.CLASSIFY_SYSTEM, congress_llm.RUBRIC_SYSTEM))}

---

# Appendix F — Field and enum reference

Every value these fields can hold. A model answer outside the list is discarded rather than
added, so an unexpected blank in the spreadsheet may mean the model returned something not
on the list.

{enum_block}
"""


# ---------------------------------------------------------------------------
# Federal executive branch
# ---------------------------------------------------------------------------
def federal_doc():
    counts = airtable_counts(["Federal Raw", "Federal Events"])
    n_sources = federal_sources.source_count()
    n_kw = sum(len(v) for v in federal_pipeline.PILLAR_KEYWORDS.values())
    n_fedreg = len(federal_sources.fedreg_specs())

    lane_titles = {"executive-action": "Executive actions", "oversight": "Oversight & watchdog",
                   "news": "Federal news", "rulemaking": "Rulemaking & notices"}
    src_rows = "\n".join(
        f"| {s['name']} | {lane_titles[lane]} | "
        f"{ {'wp_api': 'WordPress API', 'rss': 'RSS', 'html': 'scraped page'}[s['kind']] }"
        f"{' · broad beat' if s.get('broad') else ''} |"
        for lane, s in federal_sources.all_federal_sources() if s["kind"] != "fedreg-api")

    fr_agencies = ", ".join(k.upper() for _, k in federal_sources.FEDREG_AGENCIES)
    fr_terms = ", ".join(t.strip('"') for t in federal_sources.FEDREG_TERMS)
    ranks = ", ".join(f"{k} = {v}" for k, v in
                      sorted(federal_dedupe.LANE_RANK.items(), key=lambda kv: -kv[1]))

    fs_ = federal_schema
    fr_block = verbatim("\n".join(
        ["agencies (full coverage):"]
        + [f"  {slug}  ->  {key}" for slug, key in federal_sources.FEDREG_AGENCIES]
        + ["", "document types:", "  " + ", ".join(federal_sources.FEDREG_TYPES),
           "", "full-text phrases (all agencies):"]
        + ["  " + ", ".join(federal_sources.FEDREG_TERMS[i:i + 3])
           for i in range(0, len(federal_sources.FEDREG_TERMS), 3)]))
    anchor_block = verbatim("\n".join(
        "  " + ", ".join(federal_pipeline.ANCHOR_WORDS[i:i + 4])
        for i in range(0, len(federal_pipeline.ANCHOR_WORDS), 4)))
    enum_block = verbatim("\n".join(
        [f"competency:       {' | '.join(fs_.COMPETENCY_CHOICES)}",
         "relevance:        1 | 2 | 3   (blank when no competency)",
         f"lane:             {' | '.join(fs_.LANE_CHOICES)}",
         f"branch:           {' | '.join(fs_.BRANCH_CHOICES)}",
         f"verification:     {' | '.join(fs_.VERIFICATION_CHOICES)}",
         f"review_status:    {' | '.join(fs_.REVIEW_STATUS_CHOICES)}",
         "", "instrument_type:"]
        + ["  " + ", ".join(fs_.INSTRUMENT_TYPE_CHOICES[i:i + 4])
           for i in range(0, len(fs_.INSTRUMENT_TYPE_CHOICES), 4)]
        + ["", "agency:"]
        + ["  " + ", ".join(fs_.AGENCY_CHOICES[i:i + 8])
           for i in range(0, len(fs_.AGENCY_CHOICES), 8)]
        + ["", "topic_tags:"]
        + ["  " + ", ".join(fs_.TOPIC_TAG_CHOICES[i:i + 6])
           for i in range(0, len(fs_.TOPIC_TAG_CHOICES), 6)]))

    return f"""# Federal executive-branch tracker — how an item becomes a row

{HEADER_NOTE.format(today=date.today().isoformat())}

## What this tracker is

A daily feed of what the **federal executive branch is doing to itself** — the memos, rules,
guidance, workforce actions, procurements, launches, reorganizations and audits that change
how the government operates. Scored against the same four Recoding America competencies as
the state tracker, re-pointed at the federal government:

- **civil-service** — hiring, classification, pay, performance, removal, and where that
  authority sits. Schedule F, RIFs, OPM rules, SES, collective bargaining, telework.
- **procedure** — the government's own procedural and compliance burden. Paperwork Reduction
  Act, OMB circulars, OIRA review, the rulemaking process, grant administration, the FAR.
- **digital** — how the government builds, buys, staffs and oversees its **own** technology
  and data. IT modernization, FedRAMP, agency AI use, benefits systems, Login.gov.
- **incentives** — the learning loop. GAO and IG findings and whether agencies implement
  them, program evaluation, performance plans, payment integrity.

This is a **separate tracker from Congress** because the two answer different questions.
Congress is committee-shaped: who has jurisdiction, what did they hold a hearing on. This is
instrument-shaped: what did an agency actually issue, and what does it change.

Current contents: **{counts['Federal Events']} events** from {counts['Federal Raw']} raw items.

{ASK}

## The flow, in plain language

```
FOUR LANES ({n_sources} sources)
  agency press pages ─┐
  GAO reports        ─┤
  trade press        ─┼─>  filter 1: keywords  ->  filter 2: AI instrument gate  ->  raw table
  Federal Register   ─┘    (news lane only)                     |
                                             filter 3: AI clustering + classification
                                                                |
                                                           events table
```

### Stage 0 — four lanes, ordered by how directly we are hearing it

The lane is a property of the **source**, never of the model's opinion. A FedScoop story
about an OMB memo is news *about* an executive action; treating it as the instrument itself
would let trade-press coverage masquerade as a primary source.

1. **Executive actions** — agency primary sources. OPM and GSA press releases, OMB's news
   page, and OMB's memoranda listing (the M-26-xx series, which is where the real OMB signal
   is; the news page is nearly dormant). What the branch did, in its own words.
2. **Oversight & watchdog** — GAO's reports feed. Moved here from the Congress tab on
   2026-08-20, because the trade press covers GAO heavily and its reports were landing on
   both tabs with nothing to deduplicate them. Its own lane rather than "executive actions"
   for two reasons: GAO is a *legislative*-branch auditor, and at ~24 reports per three weeks
   it outweighs everything else here.
3. **Federal news** — FedScoop, Government Executive, Nextgov/FCW, Federal News Network,
   Route Fifty, Washington Technology, MeriTalk, The Hill. Second-hand, but the only lane
   that catches an action nobody announced: a draft memo, an internal directive, a RIF in
   progress. About a third of all events are single-sourced from here.
4. **Rulemaking & notices** — the Federal Register API. The legal record.

Appendix A lists every source.

### Stage 1 — the keyword pre-screen (no AI, news lane only)

The news lane's {n_kw} regular-expression patterns work exactly like the congressional
tracker's, and carry the same risk: a real action described in words nobody added to the list
is invisible from here on. Appendix B is the complete list.

**Outlets with a beat wider than the federal government must also hit an "anchor"** — a named
institution or instrument (OPM, OMB, GSA, Schedule F, executive order, Federal Register, and
so on). This exists because The Hill publishes roughly 100 posts a day across every beat, and
the capacity vocabulary alone matches an enormous amount of general political coverage on
words like "oversight", "accountability" and "AI". In one three-week window the anchor took
The Hill from 1,706 posts to 13 candidates. Appendix B lists the anchors too.

**The other three lanes are not pre-screened at all**, on purpose:

- *Executive actions* is about ten items a window, and the whole point of the lane is that a
  bland agency headline can hide a governmentwide instrument. Paying for the AI call is
  cheaper than a keyword list that has to anticipate agency prose.
- *Oversight* is low volume and almost entirely on-topic by construction.
- *Rulemaking* is already scoped by the queries themselves — see below.

### How the Federal Register is scoped — the one place we knowingly narrow

The full Register runs about **1,600 documents every three weeks**, and nearly all of it is
ordinary regulatory business — food additive petitions and the like — plus roughly 525 routine
Paperwork Reduction Act collection renewals. Reading all of it would cost about ten times as
much for a handful more events. So {n_fedreg} queries are run instead:

1. **Everything** from the {len(federal_sources.FEDREG_AGENCIES)} agencies whose subject matter
   *is* the machinery of government: {fr_agencies}.
2. **Every presidential document** — executive orders and presidential memoranda.
3. **A phrase search across all agencies** for {len(federal_sources.FEDREG_TERMS)} terms, so
   we still catch a mission agency doing something to its own machinery: {fr_terms}.

That yields roughly 200 documents, of which about 18 survive the gate. **The honest limitation
is net 3**: a capacity action at a mission agency that avoids all of those phrases is
invisible to us. This is the single most likely place for a systematic miss, and the best
thing you can do while reading is tell us which words are absent.

### Stage 2 — the instrument gate (Claude Haiku, a small fast model)

This is the filter that does the most work here, and it is stricter than the congressional
one. Agency press offices produce a great deal of language and comparatively few actions, and
the language is written to be quoted. So the test is not provenance but **instrument**: can
you name the concrete thing that happened?

Qualifying instruments: a numbered OMB memorandum or circular; agency guidance, a policy
letter, a directive or delegation; a proposed or final rule; a Federal Register notice with
legal effect; an executive order or presidential memorandum; a workforce action actually
taken (RIF, hiring authority, reclassification, pay determination, bargaining order); a
procurement action; a system launched or shut off; a reorganization; a report with findings;
a data release; a court order compelling an agency.

Not instruments — these fail: ICYMI items, interviews, podcast episodes, op-eds, transcripts;
statements praising, condemning or responding to someone; anniversaries and awards; a named
official simply arriving or departing; restatements of existing policy; announcements of
intent to be more efficient with no mechanism; analysis and explainer pieces; vendor business
news; routine PRA renewals, meeting notices and technical corrections.

Everything that passes is then **restated neutrally**. "Historic", "commonsense", "radical",
"misguided" and "restoring" are not facts. A release headlined as a partisan attack that in
substance announces a governmentwide staffing-plan requirement is recorded as the latter.
Each row also carries a link to the primary document so you can check our restatement against
the source. Appendix C is the prompt.

**Reported and draft-stage actions are kept and labelled, not dropped.** A trade outlet
describing a draft memo before it is signed is often the earliest real signal. Every row
records whether the action is `official` (published by the agency, the Register or the White
House), `reported` (a credible outlet says it happened, no primary document), or
`draft-leaked`. A reported item can still be highly relevant — uncertainty about publication
status is not uncertainty about importance.

### Stage 3 — clustering (Claude Sonnet)

One action reaches us many times over: the agency's own release, the Federal Register
document, the GAO report, and four trade write-ups, all within a day or two. This step merges
them into one event and synthesizes a neutral account, keeping every source URL. The merged
row is better than any single source — the primary lane supplies the instrument, the news
lane supplies what it means in practice.

Rows are grouped by **agency** rather than by lane, since cross-source coverage of one action
agrees on the agency. GAO and `governmentwide` are treated as reporters rather than subjects,
so a GAO report on FEMA groups with FEMA coverage instead of with other GAO reports.

**Where a cluster spans lanes, the highest-provenance member decides where it files**
({ranks}). So a Federal Register rule plus a Federal News Network story files under
rulemaking; that same rule plus OPM's own release files under executive actions; a GAO report
plus three trade write-ups files under oversight. An instrument always outranks the coverage
of it, and also outranks a finding about it — if OPM issues guidance in response to a GAO
report, the event is the guidance. Appendix D is the prompt.

### Stage 4 — classification (Claude Sonnet, against the full rubric)

Every event is classified against the complete rubric: zero, one or more competencies, a 1–3
relevance score, and topic tags. This pass is authoritative and regularly overrules stage 2,
which is why the raw and events sheets in the spreadsheet disagree. Appendix E is the federal
adaptation plus the shared rubric, exactly as the model receives them.

## Known weaknesses — the things to look for

- **The Federal Register phrase list bounds lane 4**, and the keyword list bounds lane 3.
  Both are lists a person wrote.
- **The Hill is expensive and unproductive.** In the first three-week window it fetched 1,706
  posts to reach 4 events, every one of which was already covered by FedScoop or Federal News
  Network. It is the first source we would cut.
- **Four outlets hold only about a week of history** — Government Executive, Nextgov/FCW,
  Route Fifty and Washington Technology share a platform with no API and no feed pagination.
  A missed day is a permanent hole, and a backfill can't reach back more than a week.
- **GAO's feed holds exactly 25 items**, about three weeks at its cadence.
- **Items are dated by the action, not by publication**, so a story this week about guidance
  issued in May is dated May and falls outside a 30-day view.
- **Nothing deduplicates between this tracker and the Congress one.** Moving GAO removed the
  case that was actually producing duplicates, but a committee release about an
  executive-branch action can still appear on both.
- **`none` is the right answer most of the time.** Two rules worth arguing with if you
  disagree: appropriations are `none` unless the funding *model* changes, and a named
  official being hired or fired is `none` unless the position's authority is the story.

---

# Appendix A — Source registry ({n_sources} total)

Feeds and scraped pages:

| Source | Lane | How we read it |
|---|---|---|
{src_rows}

Plus **{n_fedreg} Federal Register API queries** (rulemaking lane):

{fr_block}

---

# Appendix B — Keyword pre-screen and anchors, verbatim

Python regular expressions, matched case-insensitively against title + body. Applied to the
**news lane only**.

{keyword_block(federal_pipeline.PILLAR_KEYWORDS)}

## Machinery anchors

Required **in addition** to a keyword above, for outlets whose beat is wider than the federal
government (currently The Hill).

{anchor_block}

---

# Appendix C — Stage 2 instrument gate prompt, verbatim

Model: `{federal_llm.MODEL_GATE}`. Sent as the system prompt; the item's title, body, source,
lane and date are sent as the user message.

{verbatim(federal_pipeline.SYSTEM_PROMPT)}

---

# Appendix D — Stage 3 clustering prompt, verbatim

Model: `{federal_llm.MODEL_CLASSIFY}`.

{verbatim(federal_dedupe.CLUSTER_SYSTEM)}

---

# Appendix E — The classification rubric, in full

Model: `{federal_llm.MODEL_CLASSIFY}`. This is the entire text the classifier receives: the
federal executive-branch adaptation first, then the shared rubric, concatenated exactly as
reproduced here. It is shown with its original formatting rather than as a code block because
this is the document to argue with — if a rule here is wrong, everything downstream of it is
wrong.

{demote(federal_llm.ADAPTATION)}

{demote(federal_llm.RUBRIC)}

## E.1 — Output instruction

Appended after the rubric above by `federal_dedupe.py`.

{verbatim(task_suffix(federal_dedupe.CLASSIFY_SYSTEM, federal_llm.RUBRIC_SYSTEM))}

---

# Appendix F — Field and enum reference

Every value these fields can hold. A model answer outside the list is discarded rather than
added, so an unexpected blank in the spreadsheet may mean the model returned something not
on the list.

{enum_block}
"""


# ---------------------------------------------------------------------------
# Federal executive branch
# ---------------------------------------------------------------------------
def federal_doc():
    counts = airtable_counts(["Federal Raw", "Federal Events"])
    n_sources = federal_sources.source_count()
    n_kw = sum(len(v) for v in federal_pipeline.PILLAR_KEYWORDS.values())
    n_fedreg = len(federal_sources.fedreg_specs())

    lane_titles = {"executive-action": "Executive actions", "oversight": "Oversight & watchdog",
                   "news": "Federal news", "rulemaking": "Rulemaking & notices"}
    src_rows = "\n".join(
        f"| {s['name']} | {lane_titles[lane]} | "
        f"{ {'wp_api': 'WordPress API', 'rss': 'RSS', 'html': 'scraped page'}[s['kind']] }"
        f"{' · broad beat' if s.get('broad') else ''} |"
        for lane, s in federal_sources.all_federal_sources() if s["kind"] != "fedreg-api")

    fr_agencies = ", ".join(k.upper() for _, k in federal_sources.FEDREG_AGENCIES)
    fr_terms = ", ".join(t.strip('"') for t in federal_sources.FEDREG_TERMS)
    ranks = ", ".join(f"{k} = {v}" for k, v in
                      sorted(federal_dedupe.LANE_RANK.items(), key=lambda kv: -kv[1]))

    fs_ = federal_schema
    fr_block = verbatim("\n".join(
        ["agencies (full coverage):"]
        + [f"  {slug}  ->  {key}" for slug, key in federal_sources.FEDREG_AGENCIES]
        + ["", "document types:", "  " + ", ".join(federal_sources.FEDREG_TYPES),
           "", "full-text phrases (all agencies):"]
        + ["  " + ", ".join(federal_sources.FEDREG_TERMS[i:i + 3])
           for i in range(0, len(federal_sources.FEDREG_TERMS), 3)]))
    anchor_block = verbatim("\n".join(
        "  " + ", ".join(federal_pipeline.ANCHOR_WORDS[i:i + 4])
        for i in range(0, len(federal_pipeline.ANCHOR_WORDS), 4)))
    enum_block = verbatim("\n".join(
        [f"competency:       {' | '.join(fs_.COMPETENCY_CHOICES)}",
         "relevance:        1 | 2 | 3   (blank when no competency)",
         f"lane:             {' | '.join(fs_.LANE_CHOICES)}",
         f"branch:           {' | '.join(fs_.BRANCH_CHOICES)}",
         f"verification:     {' | '.join(fs_.VERIFICATION_CHOICES)}",
         f"review_status:    {' | '.join(fs_.REVIEW_STATUS_CHOICES)}",
         "", "instrument_type:"]
        + ["  " + ", ".join(fs_.INSTRUMENT_TYPE_CHOICES[i:i + 4])
           for i in range(0, len(fs_.INSTRUMENT_TYPE_CHOICES), 4)]
        + ["", "agency:"]
        + ["  " + ", ".join(fs_.AGENCY_CHOICES[i:i + 8])
           for i in range(0, len(fs_.AGENCY_CHOICES), 8)]
        + ["", "topic_tags:"]
        + ["  " + ", ".join(fs_.TOPIC_TAG_CHOICES[i:i + 6])
           for i in range(0, len(fs_.TOPIC_TAG_CHOICES), 6)]))

    return f"""# Federal executive-branch tracker — how an item becomes a row

{HEADER_NOTE.format(today=date.today().isoformat())}

## What this tracker is

A daily feed of what the **federal executive branch is doing to itself** — the memos, rules,
guidance, workforce actions, procurements, launches, reorganizations and audits that change
how the government operates. Scored against the same four Recoding America competencies as
the state tracker, re-pointed at the federal government:

- **civil-service** — hiring, classification, pay, performance, removal, and where that
  authority sits. Schedule F, RIFs, OPM rules, SES, collective bargaining, telework.
- **procedure** — the government's own procedural and compliance burden. Paperwork Reduction
  Act, OMB circulars, OIRA review, the rulemaking process, grant administration, the FAR.
- **digital** — how the government builds, buys, staffs and oversees its **own** technology
  and data. IT modernization, FedRAMP, agency AI use, benefits systems, Login.gov.
- **incentives** — the learning loop. GAO and IG findings and whether agencies implement
  them, program evaluation, performance plans, payment integrity.

This is a **separate tracker from Congress** because the two answer different questions.
Congress is committee-shaped: who has jurisdiction, what did they hold a hearing on. This is
instrument-shaped: what did an agency actually issue, and what does it change.

Current contents: **{counts['Federal Events']} events** from {counts['Federal Raw']} raw items.

{ASK}

## The flow, in plain language

```
FOUR LANES ({n_sources} sources)
  agency press pages ─┐
  GAO reports        ─┤
  trade press        ─┼─>  filter 1: keywords  ->  filter 2: AI instrument gate  ->  raw table
  Federal Register   ─┘    (news lane only)                     |
                                             filter 3: AI clustering + classification
                                                                |
                                                           events table
```

### Stage 0 — four lanes, ordered by how directly we are hearing it

The lane is a property of the **source**, never of the model's opinion. A FedScoop story
about an OMB memo is news *about* an executive action; treating it as the instrument itself
would let trade-press coverage masquerade as a primary source.

1. **Executive actions** — agency primary sources. OPM and GSA press releases, OMB's news
   page, and OMB's memoranda listing (the M-26-xx series, which is where the real OMB signal
   is; the news page is nearly dormant). What the branch did, in its own words.
2. **Oversight & watchdog** — GAO's reports feed. Moved here from the Congress tab on
   2026-08-20, because the trade press covers GAO heavily and its reports were landing on
   both tabs with nothing to deduplicate them. Its own lane rather than "executive actions"
   for two reasons: GAO is a *legislative*-branch auditor, and at ~24 reports per three weeks
   it outweighs everything else here.
3. **Federal news** — FedScoop, Government Executive, Nextgov/FCW, Federal News Network,
   Route Fifty, Washington Technology, MeriTalk, The Hill. Second-hand, but the only lane
   that catches an action nobody announced: a draft memo, an internal directive, a RIF in
   progress. About a third of all events are single-sourced from here.
4. **Rulemaking & notices** — the Federal Register API. The legal record.

Appendix A lists every source.

### Stage 1 — the keyword pre-screen (no AI, news lane only)

The news lane's {n_kw} regular-expression patterns work exactly like the congressional
tracker's, and carry the same risk: a real action described in words nobody added to the list
is invisible from here on. Appendix B is the complete list.

**Outlets with a beat wider than the federal government must also hit an "anchor"** — a named
institution or instrument (OPM, OMB, GSA, Schedule F, executive order, Federal Register, and
so on). This exists because The Hill publishes roughly 100 posts a day across every beat, and
the capacity vocabulary alone matches an enormous amount of general political coverage on
words like "oversight", "accountability" and "AI". In one three-week window the anchor took
The Hill from 1,706 posts to 13 candidates. Appendix B lists the anchors too.

**The other three lanes are not pre-screened at all**, on purpose:

- *Executive actions* is about ten items a window, and the whole point of the lane is that a
  bland agency headline can hide a governmentwide instrument. Paying for the AI call is
  cheaper than a keyword list that has to anticipate agency prose.
- *Oversight* is low volume and almost entirely on-topic by construction.
- *Rulemaking* is already scoped by the queries themselves — see below.

### How the Federal Register is scoped — the one place we knowingly narrow

The full Register runs about **1,600 documents every three weeks**, and nearly all of it is
ordinary regulatory business — food additive petitions and the like — plus roughly 525 routine
Paperwork Reduction Act collection renewals. Reading all of it would cost about ten times as
much for a handful more events. So {n_fedreg} queries are run instead:

1. **Everything** from the {len(federal_sources.FEDREG_AGENCIES)} agencies whose subject matter
   *is* the machinery of government: {fr_agencies}.
2. **Every presidential document** — executive orders and presidential memoranda.
3. **A phrase search across all agencies** for {len(federal_sources.FEDREG_TERMS)} terms, so
   we still catch a mission agency doing something to its own machinery: {fr_terms}.

That yields roughly 200 documents, of which about 18 survive the gate. **The honest limitation
is net 3**: a capacity action at a mission agency that avoids all of those phrases is
invisible to us. This is the single most likely place for a systematic miss, and the best
thing you can do while reading is tell us which words are absent.

### Stage 2 — the instrument gate (Claude Haiku, a small fast model)

This is the filter that does the most work here, and it is stricter than the congressional
one. Agency press offices produce a great deal of language and comparatively few actions, and
the language is written to be quoted. So the test is not provenance but **instrument**: can
you name the concrete thing that happened?

Qualifying instruments: a numbered OMB memorandum or circular; agency guidance, a policy
letter, a directive or delegation; a proposed or final rule; a Federal Register notice with
legal effect; an executive order or presidential memorandum; a workforce action actually
taken (RIF, hiring authority, reclassification, pay determination, bargaining order); a
procurement action; a system launched or shut off; a reorganization; a report with findings;
a data release; a court order compelling an agency.

Not instruments — these fail: ICYMI items, interviews, podcast episodes, op-eds, transcripts;
statements praising, condemning or responding to someone; anniversaries and awards; a named
official simply arriving or departing; restatements of existing policy; announcements of
intent to be more efficient with no mechanism; analysis and explainer pieces; vendor business
news; routine PRA renewals, meeting notices and technical corrections.

Everything that passes is then **restated neutrally**. "Historic", "commonsense", "radical",
"misguided" and "restoring" are not facts. A release headlined as a partisan attack that in
substance announces a governmentwide staffing-plan requirement is recorded as the latter.
Each row also carries a link to the primary document so you can check our restatement against
the source. Appendix C is the prompt.

**Reported and draft-stage actions are kept and labelled, not dropped.** A trade outlet
describing a draft memo before it is signed is often the earliest real signal. Every row
records whether the action is `official` (published by the agency, the Register or the White
House), `reported` (a credible outlet says it happened, no primary document), or
`draft-leaked`. A reported item can still be highly relevant — uncertainty about publication
status is not uncertainty about importance.

### Stage 3 — clustering (Claude Sonnet)

One action reaches us many times over: the agency's own release, the Federal Register
document, the GAO report, and four trade write-ups, all within a day or two. This step merges
them into one event and synthesizes a neutral account, keeping every source URL. The merged
row is better than any single source — the primary lane supplies the instrument, the news
lane supplies what it means in practice.

Rows are grouped by **agency** rather than by lane, since cross-source coverage of one action
agrees on the agency. GAO and `governmentwide` are treated as reporters rather than subjects,
so a GAO report on FEMA groups with FEMA coverage instead of with other GAO reports.

**Where a cluster spans lanes, the highest-provenance member decides where it files**
({ranks}). So a Federal Register rule plus a Federal News Network story files under
rulemaking; that same rule plus OPM's own release files under executive actions; a GAO report
plus three trade write-ups files under oversight. An instrument always outranks the coverage
of it, and also outranks a finding about it — if OPM issues guidance in response to a GAO
report, the event is the guidance. Appendix D is the prompt.

### Stage 4 — classification (Claude Sonnet, against the full rubric)

Every event is classified against the complete rubric: zero, one or more competencies, a 1–3
relevance score, and topic tags. This pass is authoritative and regularly overrules stage 2,
which is why the raw and events sheets in the spreadsheet disagree. Appendix E is the federal
adaptation plus the shared rubric, exactly as the model receives them.

## Known weaknesses — the things to look for

- **The Federal Register phrase list bounds lane 4**, and the keyword list bounds lane 3.
  Both are lists a person wrote.
- **The Hill is expensive and unproductive.** In the first three-week window it fetched 1,706
  posts to reach 4 events, every one of which was already covered by FedScoop or Federal News
  Network. It is the first source we would cut.
- **Four outlets hold only about a week of history** — Government Executive, Nextgov/FCW,
  Route Fifty and Washington Technology share a platform with no API and no feed pagination.
  A missed day is a permanent hole, and a backfill can't reach back more than a week.
- **GAO's feed holds exactly 25 items**, about three weeks at its cadence.
- **Items are dated by the action, not by publication**, so a story this week about guidance
  issued in May is dated May and falls outside a 30-day view.
- **Nothing deduplicates between this tracker and the Congress one.** Moving GAO removed the
  case that was actually producing duplicates, but a committee release about an
  executive-branch action can still appear on both.
- **`none` is the right answer most of the time.** Two rules worth arguing with if you
  disagree: appropriations are `none` unless the funding *model* changes, and a named
  official being hired or fired is `none` unless the position's authority is the story.

---

# Appendix A — Source registry ({n_sources} total)

Feeds and scraped pages:

| Source | Lane | How we read it |
|---|---|---|
{src_rows}

Plus **{n_fedreg} Federal Register API queries** (rulemaking lane):

{fr_block}

---

# Appendix B — Keyword pre-screen and anchors, verbatim

Python regular expressions, matched case-insensitively against title + body. Applied to the
**news lane only**.

{keyword_block(federal_pipeline.PILLAR_KEYWORDS)}

## Machinery anchors

Required **in addition** to a keyword above, for outlets whose beat is wider than the federal
government (currently The Hill).

{anchor_block}

---

# Appendix C — Stage 2 instrument gate prompt, verbatim

Model: `{federal_llm.MODEL_GATE}`. Sent as the system prompt; the item's title, body, source,
lane and date are sent as the user message.

{verbatim(federal_pipeline.SYSTEM_PROMPT)}

---

# Appendix D — Stage 3 clustering prompt, verbatim

Model: `{federal_llm.MODEL_CLASSIFY}`.

{verbatim(federal_dedupe.CLUSTER_SYSTEM)}

---

# Appendix E — Stage 4 classification prompt, verbatim

Model: `{federal_llm.MODEL_CLASSIFY}`. The federal executive-branch adaptation followed by the
shared rubric, concatenated exactly as shown, plus the output instruction at the end.

{verbatim(federal_dedupe.CLASSIFY_SYSTEM)}

---

# Appendix F — Field and enum reference

Every value these fields can hold. A model answer outside the list is discarded rather than
added, so an unexpected blank in the spreadsheet may mean the model returned something not on
the list.

{enum_block}
"""


def to_docx(md_path):
    """pandoc markdown -> docx. --toc gives reviewers a clickable outline, which
    matters when the appendices run to tens of pages of prompt text."""
    if not shutil.which("pandoc"):
        print("  pandoc not found — skipping .docx (brew install pandoc)")
        return None
    docx_path = md_path.replace(".md", ".docx")
    subprocess.run(
        ["pandoc", md_path, "-o", docx_path, "--toc", "--toc-depth=2",
         "-V", "geometry:margin=1in", "--wrap=preserve"],
        check=True)
    return docx_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", choices=["md", "docx", "both"], default="both")
    ap.add_argument("--out", default="review")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    today = date.today().isoformat()
    for name, builder in (("congress-tracker-walkthrough", congress_doc),
                          ("federal-tracker-walkthrough", federal_doc)):
        md = os.path.join(args.out, f"{name}-{today}.md")
        with open(md, "w") as f:
            f.write(builder())
        size = os.path.getsize(md) / 1024
        print(f"  {md}  ({size:.0f} KB)")
        if args.format in ("docx", "both"):
            out = to_docx(md)
            if out:
                print(f"  {out}  ({os.path.getsize(out) / 1024:.0f} KB)")
        if args.format == "docx":
            os.remove(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
