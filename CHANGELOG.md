# Changelog & calibration log

Two records in one file, because they answer two different questions a
newcomer to this repo will ask.

**Release history** — what the tracker did, and when it changed. One entry per
meaningful version, newest first. Written for someone who needs to know why the
system behaves the way it does today.

**Calibration log** — what the tracker *learned* about relevance, and from whom.
Every time a human reviews a window of output and that review changes a prompt,
a rubric, a keyword list, or a gate, it gets an entry here. This is the part
that must not live only in a chat window: the reasoning behind a gate is worth
more than the gate, and a model context that grows without ever being written
down is a context that eventually gets truncated and lost.

## How to maintain this file

- **On a release** — add an entry under Release history before merging. The
  commit body is usually 80% of the entry; the value this file adds is grouping
  commits into a version and saying what changed *for a user of the tracker*.
- **On a calibration round** — add an entry under Calibration log naming the
  reviewer, the corpus they reviewed, what they found, and what changed as a
  result. If nothing changed yet, say so and leave it open.
- **Rubrics are not documentation.** `rubrics/rubric.md`,
  `rubrics/congress-adaptation.md`, and `rubrics/federal-adaptation.md` are loaded
  at runtime and injected into the classifier prompts (`dedupe.py:43`,
  `congress_llm.py:19-21`, `federal_llm.py:28`, `candidates_dedupe.py:55`).
  Editing them changes model behaviour on the next run. Record such edits here
  with the reasoning; the diff shows *what* changed, this file says *why*.

Dates are the date of the work, not of the write-up.

---

# Release history

## Unreleased

### Repository restructure — 2026-08-31

Navigation only. No behaviour changed: 21 of the 29 moved modules are
byte-identical in executable logic (verified by AST comparison with imports and
docstrings stripped), and the other 8 differ only in the asset-path strings the
move forced.

- **`tracker/` package, one subpackage per government category** — `state/`,
  `congress/`, `federal/`, `candidates/`, `ecosystem/`, plus `export/`,
  `shared/`, and `digest.py`. Root went from 47 tracked entries to 12.
- **Entry points now run as `python -m tracker.<pkg>.<mod>`.** All 10 CI
  invocations migrated. Imports were rewritten in aliased form
  (`from tracker.congress import llm as congress_llm`) specifically so no call
  site in any function body had to change.
- **Assets moved out of the Python tree**: `rubrics/` (runtime-loaded),
  `docs/` + `docs/specs/` (design docs), `data/` (static inputs), `tools/`
  (standalone one-offs).
- **`tracker/paths.py`** replaces four independent `_HERE` computations for
  locating `rubrics/`. Entry points now work from any working directory.
- `.env_example` gained `RESEND_API_KEY`, `DIGEST_FROM`, and `TRACKER_URL`,
  which the digest and the workflow use but the example never documented.

### Known refactor debt

No test suite exists (0 test files, 11,144 lines of Python). Until one does,
the following duplications should *not* be consolidated — there would be no
safety net:

- `tracker/congress/dedupe.py` and `tracker/federal/dedupe.py` share 8 function
  names; federal already re-exports congressional fetch, schema, and LLM
  contracts, so the two are siblings rather than copies.
- `tracker/state/dedupe.py` and `tracker/candidates/dedupe.py` share 5.
- State dedupe windows on `date` while congress/federal window on
  `ingested_at`, and state does delete-and-rewrite where the others upsert on a
  stable key — so state loses reviewer annotations the others preserve.

- `tracker/export/review.py` — in-progress `--single-tab` work, uncommitted as
  of 2026-08-31 (one flat 'Review' sheet across the deduped layers).

## v0.8 — Federal executive branch, reviewer package, unified digest — 2026-08-20

The third and final pipeline, plus the tooling to get human eyes on all three.

- **Federal executive-branch tracker** (`federal_*.py`, `/federal` tab). Covers
  what the executive branch does to itself: OMB memoranda, OPM and GSA
  instruments, executive orders, the Federal Register, and the federal trade
  press. Four lanes — executive-action, rulemaking, oversight, news — where the
  lane is a property of the **source**, not of the model's judgement, so trade-
  press coverage of a memo can never masquerade as the memo. Where a cluster
  spans lanes, the highest-provenance member wins.
- **The gate is an instrument test, not a provenance test.** An item enters only
  when a concrete instrument can be named (a numbered memo, guidance, a rule, an
  EO, a workforce or procurement action, a launch, a reorganisation, a finding,
  a court order). Agency press offices produce a great deal of language and
  comparatively few actions, and the language is written to be quoted.
- **Federal Register scoped three ways** rather than read whole — the full
  Register runs ~1,600 documents per 21 days, nearly all ordinary regulatory
  business plus ~525 routine PRA renewals.
- **GAO moved off the Congress tracker** onto the federal one.
- **Reviewer package** (`tracker/export/review.py`, `tracker/export/docs.py`). One `.xlsx` per
  tracker carrying both the deduped events and the raw items behind them — the
  disagreement between the cheap gate's guess and the full-rubric pass is
  exactly what a reviewer should look at. Rows matching no competency are shaded
  rather than hidden, because checking for false negatives is the most valuable
  thing a reviewer can do. `tracker/export/docs.py` writes a plain-language walkthrough
  per tracker with every prompt, keyword list and enum read out of the live
  modules at build time, so a prompt edit cannot leave the document describing a
  pipeline that no longer exists. Both exports are one-way on purpose: Airtable's
  `review_status` / `reviewer_notes` stay the single source of truth.
- **Digest restructured** to cover both halves (STATE: four competencies then
  Governors '26; FEDERAL: the week's calendar, then Congress, then agencies).
  Every section now renders through one item shape. State shows all four
  competencies even when empty; federal omits empty ones and deduplicates across
  sections, because federal `incentives` is nearly co-extensive with "a watchdog
  published something" and was restating most of the other two sections.
- **Federal pipeline runs daily**, both stages — two of the three lanes are
  perishable (Government Executive and Nextgov hold ~7 days of feed, The Hill
  ~2), so a missed day is a permanent hole.

## v0.7 — Congressional tracker — 2026-08-13

- Covers the seven committees that govern how the federal government runs itself
  (HSGAC, Senate/House Rules, Senate/House Approps, House Oversight, House
  Admin), plus both whips, GAO, and CBO.
- **Two independent ingest paths.** Press/activity: 29 sources → Congress Raw →
  Congress Events (15 RSS, 11 HTML scrapes, HSGAC and Padilla via WordPress REST).
  Hearings and bills: the Congress.gov API → Congress Hearings / Congress Bills,
  with no clustering stage, since one API record is one hearing or one bill with
  a stable ID. This replaced six planned HTML hearing scrapers.
- `rubrics/congress-adaptation.md` re-points the four competencies at the federal
  government and is prepended to the shared `rubrics/rubric.md`, which is unchanged.
- **Two deliberate departures from the state pipeline**, both still true today:
  Congress Raw carries `ingested_at` and windows on it (the state `dedupe.py`
  windows on `date`, so an item ingested today about a six-week-old action falls
  out of every future window — see README known gaps); and clean tables upsert on
  a stable key instead of delete-and-rewrite, preserving `review_status` /
  `reviewer_notes` across nightly runs.
- Extracted three shared modules rather than adding more duplication:
  `airtable_util.ensure_table` (was pasted in five files),
  `web/app/lib/airtable.fetchTable` (inlined in four routes), and
  `web/app/lib/competencies`.
- Congress tab: GAO/CBO in their own section (GAO alone was 18 of 30 shown
  events and buried committee activity), collapsible rows, bill summaries.
- Fixed a silent bug where `apply_classification` routed every bill summary to a
  field the bills table doesn't have — bills had had no summary at all.
- 21-day backfill: 33 events, 4 hearings, 138 bills.

## v0.6.1 — 2026-07-20

- Digest sends from the recodingamerica.org Resend account address.

## v0.6 — Candidate dedupe layer — 2026-07-15

- `tracker/candidates/dedupe.py` mirrors the main tracker's raw→clean split, clustering
  raw developments per candidate and re-classifying against the full `rubrics/rubric.md`.
  **Cut RAF-relevance from 82% to 32%** on the seed corpus (87 articles → 41
  developments) — the raw Haiku gate was far too permissive alone.
- `tracker/candidates/pipeline.py` raw gate is now two gates like `pipeline.py`
  (governing agenda AND touches ≥1 competency), enforced in code rather than
  only in the prompt. Drops tax/healthcare/crime plans.
- Digest gains a Gov Candidates Corner.

## v0.5 — Governors '26 candidate tracker — 2026-07-06

- Standalone sibling pipeline for the 2026 gubernatorial races: hand-curated
  roster (`tracker/candidates/seed.py`), daily Google News gate+classify, static
  per-candidate platform scrape, and a feed-first `/candidates` tab.

## v0.4 — State Specs + weekly digest — 2026-06-26

- **State Specs**: a static one-row-per-state reference layer alongside the live
  feed, every value source-backed with as-of dates, plus a profiles UI with a
  compare table and per-state pages. `partisan_lean` rule locked: Purple iff
  |2024 presidential margin| < 4.0, otherwise Red/Blue by direction.
- **Weekly email digest** (`digest.py`) via Resend, after the Monday dedupe.
  Selection rule: all relevance-3 events, topping up with 2s only when a category
  has ≤4 threes. Recipient source and provider call were isolated from the start
  so a subscriber model could drop in later.
- Ecosystem tracker and gov-releases working files committed as-is.

## v0.3 — Rubric-based competency classification — 2026-06-22

The classification model the tracker still uses today.

- **Retired pillars and 1–5 significance.** Classification moved out of
  per-article gating and into a per-event step driven by `rubrics/rubric.md`, returning
  `{competency, relevance, topic_tags}`.
- **Competency became multi-valued** (zero or more, not exactly one). An event
  can genuinely span two — oversight of a failing benefits/IT system is both
  digital and incentives. An empty list means it fits none.
- `digital` explicitly includes data-privacy and AI-governance laws that reach
  the government's own technology, systems, or data; only purely private or
  consumer laws stay out.
- Web view gained independent competency pills and a separate "Show other
  activity" checkbox, off by default.

> **Note for anyone debugging an empty-looking tracker:** the default filter
> hides no-competency events. Combined with the Monday-only state dedupe, this
> accounts for most "the tracker looks broken" reports.

## v0.2 — Daily ingest — 2026-06-11

- **Ingest moved to daily; dedupe stays Mondays.** 94 of 171 feeds retain <7 days
  and 44 of those cannot be paginated backwards (Arc-platform papers, public
  radio), so a weekly pull silently lost mid-week items. Ingest is idempotent, so
  daily runs only add what's new.
- Event list paginated, 10 per page. Capitol-dome favicon.

## v0.1 — Initial tracker — 2026-06-08 / 06-09

- `pipeline.py`: States Newsroom + newspaper + trade-press ingest across 171
  RSS-verified feeds in all 50 states, with WordPress feed pagination, a keyword
  pre-screen, and provenance gates. One row per article into Raw Events.
- `dedupe.py`: clusters raw rows into one event per government action, merging
  sources; rebuilds only its date window.
- Next.js map view with time/pillar/activity/actor filters; Sources &
  methodology tab rendered from a `sources.json` snapshot so it stays in sync
  with the registry the pipeline actually uses.
- Feed fetching hardened so one outlet's CDN error can't kill a whole run — a
  raw socket error escaping feedparser had already done exactly that.

---

# Calibration log

## 2026-08-28 — Congress and federal validation round (Taylor Swift, Anna Heetderks)

**Corpus.** ~50 scraped events each: Taylor on Congress, Anna on federal
executive branch. Each marked include/exclude with notes, plus a
good-for-state-capacity / bad-for-state-capacity label.

**What held up.**
- Competency tagging was accurate on both sides. Taylor: no issues on Congress.
  Anna: "pretty good at getting the competencies right", minor tweaks only.
- The four competencies for procedure, rules and admin were "pretty spot on".
- OPM coverage surfaced material Anna would not otherwise have seen, correctly
  categorised against the civil service competency.

**What needs work.**
- **Post office bills.** ~50 of them in the Congress corpus. They are correctly
  tagged as no-competency and so hidden by default, but they dominate the raw
  feed and will recur across many committees. Worth a cheaper pre-gate.
- **The good/bad-for-state-capacity label is too fraught to keep as posed.**
  Anna's example: OPM's guidance on disparate impact in hiring assessments — the
  field is genuinely divided on whether that is good or bad. Decision: use these
  labels to improve *how the summaries are written* rather than to train a
  good/bad verdict field.
- **`why_it_matters` summaries are weak** — hyperbolic, and generated by too
  small a model. This is the highest-leverage fix from the round.
- **`incentives` is a catch-all.** Partly because the competency isn't settled
  internally; anything with "feedback" or "oversight" in it falls in. Usually
  harmless but worth watching.
- **Exec-branch edge cases.** A large Oracle contract solicitation is relevant in
  a different *way* than an OPM rule finalisation is. Anna errs toward over-
  inclusion. Unresolved: whether to scope down, or to let the product format
  carry the distinction.
- **GAO items have two layers** — what the report says about GAO, and what GAO
  found. The tracker currently doesn't distinguish them.

**Structural limitation named.** Reviewers can only validate false positives.
Nobody can see what the scraper *didn't* pick up, so precision is measurable and
recall is not. Any future round needs a designed recall check — e.g. hand a
reviewer a known-relevant item and see whether it appears.

**Timing caveat.** August recess: little legislation introduced, and what comes
next is largely omnibus. Congressional precision won't be truly testable until
January–February. Omnibus coverage is expected to be manageable (~26 hits from
13 subcommittees per chamber) but shutdown periods will produce daily press
releases with very high-level content.

**Status: open.** Labels not yet folded into the prompts and rubrics.

## 2026-07-15 — Candidate gate tightened (internal, seed corpus)

Raw Haiku gate alone produced 82% RAF-relevance. Adding the clean-layer
re-classification against the full `rubrics/rubric.md` cut that to 32% (87 articles → 41
developments), and the raw gate was split into two enforced-in-code gates
(governing agenda AND ≥1 competency) to drop tax/healthcare/crime plans. The
lesson generalised: a cheap single-model gate is not a substitute for a
full-rubric pass on the clean layer.

## 2026-06-22 — Competency model corrected against real events (internal)

Single-valued competency was forcing false choices on real events — oversight of
a failing benefits/IT system is genuinely both digital and incentives. Made
multi-valued. Separately, data-privacy and AI-governance laws reaching the
government's own systems were being excluded as "private sector"; `rubrics/rubric.md` now
includes them explicitly.
