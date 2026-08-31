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

### why_it_matters rewritten against a blind A/B — 2026-08-31

The line under every event on the tracker and in the digest was specified, in four
files, as `"why_it_matters": "one line for a Recoding America reader, empty string if
none"`. That was the entire instruction. The model filled the vacuum with the only
vocabulary it had — the rubric's — so 11% of lines contained "capacity", 5% "machinery",
and most restated the competency the reader could already see on the chip.

`tracker/shared/wim.py` now holds the spec in two variants, imported by all five places
that generate the field (the four dedupes plus `congress/api_sync.py`, which writes
bills and hearings).

- **RULES** (state, congress, federal): name something concrete from this event; say
  what the title and summary do not; never restate the competency; say the smallest true
  thing about routine housekeeping rather than inflating it.
- **CANDIDATE_RULES** (governors '26): deliberately permits what the general rules
  forbid — naming plainly what kind of governing action it is, and placing it in the
  race. The substance stays the subject; the race may appear only as a trailing clause.
- **Both:** stop at what is known (no "whether X is the open question", no guessing at
  intent, no predicting unobserved outcomes); absolute grounding; flat register; 30
  words; never empty.

How the rules were earned, since none of this should be re-derived on instinct:

- **Blind A/B over 60 events** — 20 from the Taylor/Anna validated rows (inclusion
  already settled, so prose was the only variable), 30 state, 10 candidates, all four
  competencies in each group, same model both sides. Revised won 36-20-4. The split
  mattered more than the total: congress 85%, federal 69%, state 63%, **candidates 20%**.
- **The candidate loss produced the fork.** Every candidate line preferred did one of two
  things the general prompt banned: placed the action in the race, or named the action
  type plainly. For an enacted rule the reader wants the mechanism; for a candidate, what
  it reveals about how they would govern.
- **The tail ban came from the notes, not the scores.** "Whether X is the open question"
  appeared in 17 of 60 revised lines and drew 8 of 18 comments — usually on lines marked
  as winners. It did not predict losing (58% vs 60%), so it was a quality defect the
  scores could not see.
- **Round 2 on the 20 hardest rows:** general rules won 9 of 10 against rows that had
  already drawn complaints. The candidate fork half-worked (4-4-2) because it
  overcorrected — lines making the campaign the subject appeared in 0 of 4 winners and 3
  of 6 losers. Hence substance-is-the-subject, and the ban on "first concrete", a tic in
  6 of 10 lines.
- **Grounding was added after the model invented statistics.** Told to name concrete
  detail, it supplied "~2.9 million federal employees enrolled in FERS", "roughly 6,000
  WV state employees", "roughly 30 other states" — none in the source. Seven of the 16
  lines carrying numbers had untraceable ones; the rule took that to zero.
- **A terse final checklist was needed because prose rules dilute.** Verified end-to-end,
  the candidate variant produced 31-34 word lines with a banned tail and the word
  "capacity", even though the same rules held in isolation — the test harness had a
  retry-on-overlength loop the pipeline does not. A numbered check at the end of the
  prompt fixed it: candidates now run 25-29 words, general 16-22, no banned vocabulary.

The two raw-layer prompts (`state/pipeline.py`, `candidates/pipeline.py`) keep the old
one-liner. Their output is overwritten by the dedupe pass and never surfaces.


### Governors '26 — the classifier was reading headlines, not articles — 2026-08-31

A diagnostic across all 87 active candidates and 2,227 articles found the
candidate tracker keeping **5 items in a week, and zero from any of the ten
competitive races**. The cause was not the gates being too strict.

- **The classifier never saw the articles.** `candidates/pipeline.py` stored the
  Google News RSS `<description>` as the article body, but for a search feed
  that field is the headline plus the outlet name — median 101 characters, and
  100% of them merely restating the title. The `[:1500]` truncation had never
  once been reached. Both gates were being asked to judge a governing agenda
  from a headline, and 26% of rejections cited, in the model's own words, that
  there was no text to read. Results are now resolved to the publisher URL with
  `googlenewsdecoder` and the article fetched before classification.
  A controlled A/B on one Wisconsin article: headline stub → `keep:false`
  ("body text is empty/missing"); real 2,586-char article → `keep:true`,
  competency `incentives`. A horse-race control was correctly rejected both
  ways, so this restores recall without costing precision.
- **Headline-only fallback.** Some publishers (The Hill, Politico) return 403 to
  any crawler, honest user-agent or not. Those items are marked headline-only
  and the prompt is told to judge the headline on its own merits and to stop
  rejecting for absent text.
- **The permitting boundary was mis-drawn.** The gate read every data-centre
  story as private-sector economic regulation and dropped it — nationwide, in
  the middle of the biggest state-capacity story of the cycle. A state changing
  how *it* approves, permits, licenses, sites or subsidises something is
  changing its own machinery. Now explicit in the prompt.
- **The per-candidate cap was selecting, not bounding.** `entries[:30]` was
  applied to Google's *relevance*-ordered list before any date filter, silently
  discarding 30% of the week and binding on exactly the highest-profile
  candidates. Entries are now date-filtered and sorted before the cap, which
  rose to 100.
- **The dedupe back-dating bug was present here too.** `candidates/dedupe.py`
  windowed on `date` (publication) while `ingested_at` sat unused in the same
  table, so anything ingested late fell out of every future window — 16 rows
  permanently orphaned, six in one week, all of which had already passed both
  gates. Now windows on `ingested_at`. Widening the raw selection alone would
  have broken the clean-table rebuild (a row published outside the window
  produces a clean row the clear step would miss, duplicating on re-run), so the
  rebuild floor is derived from what was actually selected and is never narrower
  than the old window. Measured on live data: 8 → 31 rows selected in one
  window, recovering 23 tagged developments.
- **`news_query` was unreachable.** The per-candidate search override has been in
  the schema since the table was created, but `seed.py:row_from_candidate` never
  populated it, so 0 of 121 rows had one. Now passed through. Default queries
  also OR in name variants, since the roster stores legal names and the press
  uses shorter ones: `Helena Buonanno Foulkes` 14 → 26 results. Nicknames
  ("Dan" for "Daniel") still cannot be derived and need the override.
- **`source_urls` now stores the publisher URL** rather than the Google
  interstitial, since the redirect is resolved anyway. The dedupe key is
  unchanged. Fixes dead links in both the web tab and the digest.
- **The candidates tab gained "Show other activity."** It filtered out
  no-competency developments unconditionally, unlike the state map which has the
  same filter with a toggle — hiding 12 of 22 rows with no way to reach them.

Still outstanding: the roster needs Elaine Pelino (RI GOP front-runner, absent
entirely), the Oklahoma runoff and Alaska certification resolved, and Andrea
James's party corrected — see the calibration log.

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

## 2026-08-31 — why_it_matters prose calibration (Atharv, blind A/B)

**Corpus.** 60 events (20 validated Congress/Federal, 30 state, 10 candidates), two
versions each from the same model, A/B randomised, marked blind. Then a second round on
the 20 hardest rows, three-way.

**Round 1:** revised 36, current 20, both bad 4 — congress 85%, federal 69%, state 63%,
candidates 20%. **Round 2:** general rules 9 of 10; candidates 4-4-2.

**What the notes taught that the scores did not.** The most repeated complaint — the
em-dash speculative tail — did not predict losing (58% vs 60%). It appeared on lines
marked as winners: *"B is better ALL BEFORE THE EMM DASH"*, *"better EXCEPT FOR THE
'WHETHER THAT PRODUCES'"*. Scores said which version to ship; notes said what was still
wrong with the winner. Run both, and read the notes on the rows you won.

**Stated preferences worth keeping:**
- No guessing at intent. Reviewer's own rewrite: *"Peters is pushing for public pressure
  that helps convert IG findings into binding action"*, not *"Peters is betting that..."*.
- No guessing at impact not yet observed — *"making a guess at its impact/output, that we
  don't actually know yet"*.
- Flatter register: "rare" → "noteworthy"; "the chronic chokepoint" → "a chokepoint";
  "recurring political awkwardness" is too editorialised.
- Candidates want the race as context and the action type named — the opposite of the
  general rules.

**Deliberately not implemented.** That with vendor contracts the risk is whether the
*vendor* delivers, not just whether the agency can absorb the tools. That is an RA
position, not a writing rule; it belongs in the rubric, where it would also affect
classification. **Still open.**

**Two rows were flagged as bad events, not bad prose** (FL Independence Day holiday, a
DHS Senate Democrats press release) — feedback for the gate, not this prompt.

**Fixture.** `review/REVIEWED-why-it-matters-comparison-2026-08-31.xlsx` and
`review/REVIEWED-why-it-matters-ROUND2-2026-08-31.xlsx`. Re-run the comparison before
changing `tracker/shared/wim.py`.

## 2026-08-31 — Governors '26 funnel diagnostic (automated, full roster)

**Corpus.** All 87 active roster candidates across 36 states, 2,227 Google News
articles in a 7-day window, every one re-classified with the production prompt
and model. Read-only; no writes.

**Finding.** 2,227 → 5 kept. **Zero of 621 articles across the ten competitive
races passed gate 1.** The cause was upstream of the rubric entirely — the
classifier was being handed headline stubs, not articles. Drop taxonomy:

| bucket | n | % |
|---|---:|---:|
| gate 1 — horse-race / off-agenda | 910 | 62.7% |
| gate 1 — explicitly "no substantive content" | 377 | 26.0% |
| gate 2 — no competency | 157 | 10.8% |
| kept | 5 | 0.2% |

**The prior hypothesis was wrong and is worth recording as such.** The standing
theory was that gate 2 was mis-specified for campaign coverage — that candidates
campaign on tax and crime, not governing machinery, so the competency test
structurally rejected everything real. Gate 2 accounts for only 11% of drops.
The gates were well-specified; they were starved. Fixes are in the release entry
above.

**The one genuine rubric miss** was the boundary between the state's own
machinery and private-sector regulation: every data-centre story nationwide was
being dropped as "economic regulation" when pausing state *approvals* is a
change to the state's own permitting. Now explicit in the prompt.

**Roster hygiene — found, not yet applied.** These are Airtable edits, listed so
they are not lost:

- **Elaine Pelino (RI, R) is missing from the roster entirely** despite leading
  Guckian 37–17 for the Sept 8 primary — she generates zero coverage because she
  does not exist in the system. Guckian is wrongly `presumptive-nominee`.
- **OK is overdue:** Mazzei won the Aug 25 runoff (50.28%), Drummond conceded;
  both still sit at `runoff-pending`.
- **AK certified 2026-08-31:** Wilson and Bronson advance → `primary-winner`;
  Taylor and Bishop → `defeated`; Walker likely defeated (medium confidence,
  verify against certification). Kreiss-Tomkins still has no platform pass.
- **Andrea James (MA)** is recorded as an Independent skipping the primary; she
  is on the Sept 1 **Democratic** ballot.
- `primary_held` unset for NY.

Worth stating plainly: fixing every roster row moves the funnel from 5 keeps to
roughly 5. Roster staleness is real hygiene debt but was **not** the volume
problem. Of 121 rows, 34 are correctly `defeated`/`withdrawn` and skipped — a
real and intended post-primary volume drop that should not be mistaken for a
leak.

**Not yet done.** Failed items are never recorded, so each is re-fetched and
re-classified daily for 7 days — ~10,500 Haiku calls/week to produce ~3 rows,
and it means the effective gate is "pass at least once in seven nondeterministic
tries." Persisting rejects with a `kept` boolean would make future drops
diagnosable without a re-run.

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
