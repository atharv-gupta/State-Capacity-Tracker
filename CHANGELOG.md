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

### Review export: one tab for a reviewer — 2026-09-03

`export_review.py --single-tab` flattens the deduped layers onto one shared
column set. A reviewer asked to read a workbook should not have to learn which
of four sheets a row lives on: the question being asked is identical for a
committee letter, a hearing and a bill. Each column takes the first field a
given row type actually carries — a bill has a `sponsor` where an action has an
`actor`, a hearing's prose lives in `agenda_summary` rather than `summary` — and
each spec gained a `kind` label so the flattened sheet can still say what a row
is.

The raw layers are deliberately excluded. They answer a different question ("did
the gate drop something it shouldn't have?") against a different field
(`pillars`, not `competency`), and mixing them in would put two incompatible
classifications in one column.

### Digest: the state leads the headline — 2026-09-03

State events and Governors '26 items printed the state postal code in the faint
12px meta line under the headline, where it was too small to scan — and the
state loader was actively *stripping* the `MD — ` prefix that `Events.Name`
already carries. The state now leads the headline instead:

    MD: State university system agrees to negotiated pay raises
    WI: Executive directive restricting county Flock surveillance camera use

- **Removed from the meta line in both sections**, so it is not printed twice.
  State events now read `budget · MD Governor's Office`; governors items read
  `David Crowley (D) · Toss-up · 3 sources`.
- **The `Name` prefix is the fallback** where a row has no `state` field, so a
  legacy row still gets its code.
- **The dry-run governors block** dropped its separate state column, which the
  headline now carries.
- Both renderers pick this up from `item["title"]`, so HTML and plain text moved
  together.

### Defaults: seven days, competitive seats, new banner line — 2026-09-03

Three unrelated defaults, changed together.

- **Seven days is the default window on every tab.** Congress, Federal and
  Governors '26 opened on 30 days; the State Map already opened on Week. The
  `hasFilters` tests and the Clear buttons on Congress and Federal were keyed to
  the old default and moved with it, so "clear" still returns to what the page
  loads with rather than silently leaving a filter on.
- **Governors '26 opens on competitive seats.** `ratingF` defaults to
  `competitive`, which `ratingClass` defines as anything that is not a Toss-up
  or a Lean — 21 of the 87 live candidates, across 10 states. The All pill is
  unchanged and one click away.
- **The banner sub-line** is now "What governments are doing in the world of
  state capacity", replacing "What state governments are actually doing, in
  Recoding America's capacities". The same sentence is the document
  `description` in `layout.js`, so it moved too — the tab title and the share
  preview would otherwise contradict the banner.

What the seven-day default actually shows, measured on 2026-09-03 against the
live payloads, competency filter at its own default:

| Feed | 7d | 30d | 90d |
|---|---|---|---|
| Federal events | 19 | 78 | 87 |
| Congress activity | 2 | 13 | 18 |
| Congress hearings | 1 | 3 | 8 |
| Congress bills | 1 | 9 | 20 |
| State events | 4 | 29 | 88 |
| Candidate developments (competitive) | 8 | 18 | 26 |

Federal and candidates read fine. **Congress opens nearly empty** — 2 activity
rows, 1 hearing, 1 bill — because its cadence is committee-shaped and slower
than a news feed's. Left at seven days as asked; if it reads as broken rather
than as quiet, that tab is the one to reconsider.

### One prose block per event on the Federal and Congress tabs — 2026-09-03

An expanded federal news row printed the same event three times: `headline` as
a full sentence (median 23 words), `summary` opening on the same facts in
identical grey 12.5px type 2px below it (median 55 words), then
`why_it_matters` (median 22). Six stacked blocks, a median of **104 words of
prose**, and a `.whymatters` rail nested inside `.itembody`'s own rail. On the
Pentagon/ChatGPT row all three blocks said "DoD approved ChatGPT for
unclassified use after a security review"; only one clause in the whole 74
words — "does not extend to classified military networks" — appeared once.

The dropdown now renders one prose block: `why_it_matters`, falling back to
`summary` where it is empty. The title already carries what happened; the why
is the one thing it cannot carry. Styled `.itemsummary` rather than
`.whymatters`, because the blue rail exists to separate the why from a summary
above it and there is no longer one to separate from.

- **The fallback is not cosmetic.** 29 of 137 `Federal Events` (21%) carry no
  `why_it_matters`, and not as legacy data: `dedupe.single_row_event` hardcodes
  it empty, so any raw row alone in its agency group that window skips the
  cluster call that would have written one. Rulemaking is worst hit (13 of the
  29) — a term sweep routinely pulls one document from an agency nothing else
  covered. `Congress Events` has 1 of 33. Without the fallback those rows would
  expand to a drawer holding no prose at all. Measured against the live
  payloads afterwards: 108 federal rows show the why, 29 the summary, **0 show
  nothing**; congress 32 / 1 / 0.
- **Federal `ActionItem` and Congress `ActivityItem`** only. Hearings and bills
  keep both blocks: their first block is an agenda or a bill summary, which is
  not a restatement of the title.
- **`hasMore` is keyed to what the body can actually show** — either prose
  field, the actor/status line, or the tags. Keying it to the why alone would
  have hidden the tag and source rows on a row that has no why.
- **Nothing changed in the data.** `headline` and `summary` stay on the API
  payload and in Airtable; the digest and the review export read them.

The raw-layer fix — having the federal gate produce a `why_it_matters` the way
the candidates pipeline now does, so single-row events get a real one instead
of a summary — is still open, and is the better answer for those 29 rows.

### Rulemaking titles no longer lead with the search phrase — 2026-09-03

Nine rows on the Federal tab's Rulemaking & notices lane rendered as
*"improper payments — Privacy Act matching program notice for Do Not Pay"* —
a lowercase phrase, an em dash, and then the actual title. The phrase was the
Federal Register full-text query that found the document, leaking out of the
source name and into the reader's view.

Three things had to line up for it, and each one is defensible alone:

- `sources.fedreg_specs` names every term query `FR term — improper payments`
  so the dry-run funnel reports yield per query, and leaves `agency` empty
  because a term sweep is not agency-scoped.
- `pipeline.build_row` labels a raw row `f"{agency or outlet} — {name}"`, and
  with no agency and no `outlet` on the spec, `outlet` fell back to the spec's
  whole name: `FR term — improper payments — Privacy Act matching…`.
- `dedupe.single_row_event` recovers the title with `split(" — ", 1)[-1]`,
  which peels off exactly one segment. It assumes the label holds no em dash.

Only the 18 term queries were affected — the `FR agency —` and `FR type —`
specs carry a real agency slug, so their label is a bare `mspb` or
`white-house` and the strip lands where it should. Only single-article rows,
too: a clustered event takes its name from the model, not from the raw `Name`.

- **The term specs now declare `"outlet": "Federal Register"`**, which is both
  true of every document they return and already what `/api/federal` displays
  for a source named `FR *`. The label holds no delimiter, so the strip works.
- **`source` is untouched**, so the funnel keeps per-query granularity and a
  term that stops matching is still visible as its own row.
- **`tools/strip_fr_term_prefixes.py`** backfills the 14 raw rows and 9 event
  rows already written. The raw half is the half that matters: the dedupe
  re-reads raw rows by `ingested_at` and upserts on `event_id`, so fixing only
  the clean table would have let the next run write the phrase back.
- **The digest had the same leak on a second surface**, found while sending a
  test copy: it labelled federal links with the raw `source_outlets` string, so
  three links read "FR term — improper payments" and three more "GAO reports".
  `digest.py` now normalises them through `federal_outlet()` — the same map the
  web route has had. Only 'Federal Events' carries registry-shaped outlet names
  (13 of its 20 distinct strings); 'Congress Events' has none, so the congress
  loader is left alone.

### Candidate developments carry a short title — 2026-09-03

The Governors '26 section of the digest read as the longest thing in the email
even after the cap of five landed, because it had no title field to print. Every
other stream carries a short title next to the sentence — `short_title` on
Congress and Federal events, a titled `Name` on state events — and candidates
carried only `headline`, which both writers prompt for as *"one plain sentence:
what the candidate said/did"*. The digest printed that sentence as the bold card
title. Measured across the 175 rows of `Candidate Events`:

| Field printed as the card title | Median | Max | Over 15 words |
|---|---|---|---|
| `Candidate Events.headline` | **21 words** | 55 | 73% |
| `Federal Events.short_title` | 9 words | 13 | 0% |
| `Congress Events.short_title` | 9 words | 11 | 0% |
| `Events.Name` (state) | 9 words | 15 | 0% |

Nothing truncates in the renderer, so the median card ran ~44 words of text
before its meta and link lines — roughly twice any other section's, five times
over.

- **The short title already existed and was being thrown away.** The cluster
  prompt has always returned `name` — *"concise title of the development, 5-10
  words, no candidate name, sentence case"* — and `build_clean_row` used it only
  as an empty-`headline` fallback, so it never reached Airtable. It is now
  stored as `short_title`.
- **The raw gate is asked for one too.** 118 of 175 rows (67%) are
  single-article and bypass the cluster call entirely — the same shape as the
  `why_it_matters` split — so the clean-layer fix alone would have missed two
  thirds of the table. `candidates/pipeline.py`
  now asks for a 6-12 word `short_title` and `single_row_development` carries it
  through.
- **The digest reads `short_title or headline`**, the same fallback the congress
  and federal sections use. Rows written before the field existed keep printing
  the sentence rather than going blank; both tables auto-create the column on
  their next run.
- **Takes effect as rows are rewritten, not retroactively.** Clustered
  developments get a short title on the next `candidates/dedupe.py` run whatever
  their raw rows look like, since the cluster call mints `name` itself.
  Single-article rows need a raw row scraped after this change, so the older
  two thirds of the table keeps falling back until it ages out of the window.

### State dedupe runs daily — 2026-09-02

The clean `Events` table refreshed only on Mondays, so the dashboard was stale
by up to six days — one of the two documented reasons the tracker "looked
empty" mid-week. It now clusters every day, immediately after its own ingest,
the pairing congress and federal already used.

The cadence change is three lines of `weekly.yml`. It was gated on two fixes
that had to land first, and **the order was the point**: run daily against the
old delete-and-rewrite code and every event in the trailing week would have
been deleted and re-created with a fresh record id *every day*, multiplying the
damage rather than fixing the staleness.

- **`Raw Events` gained `ingested_at`, and the dedupe windows on it** instead of
  the LLM-extracted action `date`. The gate backdates `date` to the government
  action, so an article scraped today about a six-week-old action carried a
  six-week-old date and fell outside every future window — it never clustered at
  all. Measured on the 428-row table: **56 rows (13%) had an ingest lag over 7
  days** and were structurally unreachable; widening the current 7-day window
  recovered 7 rows (24 → 31). Rows predating the field fall back to `date`.
- **`Events` is upserted on a stable `event_id`** instead of being deleted and
  rewritten. Writes go through `shared.airtable.upsert` with
  `preserve=REVIEW_FIELDS`, and the table gained `review_status` /
  `reviewer_notes` — a human verdict on a state event previously had nowhere
  durable to live.
- **An event is written once and then only accretes sources.** `event_id` is
  minted at first sighting and never changes. Later runs match a cluster to an
  existing event by **source-URL overlap**, not by re-hashing its URL set: the
  set grows as more outlets cover the same action, so a content hash would
  change and mint a duplicate. A matched event gets its provenance updated
  (`source_urls`, `source_outlets`, `source_type`, `article_count`) and every
  `FROZEN_FIELDS` value left as first written — `headline`, `Notes`,
  `why_it_matters`, `date`, `competency`, `relevance`, `topic_tags`, actor
  fields. Nothing is deleted: under first-writer-wins nothing is superseded by
  re-clustering, so `state/dedupe.py` no longer prunes.
- **The steady state is free.** A state whose every windowed article already
  belongs to an event is skipped before any LLM call. Verified end to end:
  run 1 → 29 new events, 29 classify calls; run 2 over the same window → 20 of
  20 states skipped, "Nothing new to cluster", zero model calls and zero
  writes; then with one article artificially marked unseen, it re-attached to
  its existing event with **all 12 frozen fields byte-identical**, same record
  id, same `event_id`.
- **`--reclassify`** regenerates the frozen fields for events already in the
  table, for a `rubrics/rubric.md` edit. Verified to change no `event_id` and no
  record id (29/29 stable) while re-writing `headline` on 16 of 29 and
  `why_it_matters` on 18 of 29.
- **Migration:** `tools/backfill_state_ingested_at.py`, run once, three steps in
  order. It fills `ingested_at` from each row's Airtable `createdTime` — which
  *is* the moment the pipeline wrote the row — rewrites the old `uuid4`
  event_ids into hashes so the first upsert updates rows rather than
  duplicating them, and collapses any rows left sharing an id (keeping one that
  carries a human verdict over one that doesn't, then the most recent). Ran
  against 428 raw and 343 clean rows; idempotent on re-run.
- **One fossil duplicate collapsed.** Exactly one pair shared a URL set: the
  same single NH veto article, written twice, dated 07-11 and 07-13 a week
  apart. That's the old path's signature — it cleared clean rows whose `date`
  fell in the window, so a row the clusterer re-dated *out* of the window
  survived the clear and got a twin. Neither `upsert` nor `prune_orphans` can
  collapse such a pair alone: they share an id, so the upsert index keeps one
  and the prune skips both. Hence step 3 of the migration.

Two things this deliberately did **not** change:

- **Candidate dedupe is still Mondays-only.** `candidates/dedupe.py` already
  windows on `ingested_at` but is still delete-and-rewrite, so daily would churn
  every row in its window every day. It wants the same upsert first.
- **Freezing the text is deliberate, and it has a cost.** An event first seen
  through one thin article keeps that article's headline, summary and
  competency even after five more outlets cover it. That bites hardest on
  `competency`: the default web view hides competency-empty events, so an event
  classified `none` on thin early evidence stays hidden even once later coverage
  makes the capacity angle obvious. `--reclassify` is the escape hatch.

  Attribution for *why* freezing was needed — measured on two consecutive runs
  of the pre-freeze code, split by whether the state called the clustering model:

  | | events | `headline` changed | `why_it_matters` changed |
  |---|---|---|---|
  | states with >1 article (`cluster_state` ran) | 17 | 16/17 | 17/17 |
  | states with 1 article (LLM bypassed) | 11 | 0/11 | 0/11 |

  The drift was entirely the clustering call, not the classifier — a
  single-article event already copies its raw row verbatim. So caching the
  classify call alone would not have fixed it; the synthesis had to freeze too.

**A one-time catch-up recovered the rows the old bug had stranded.** After the
switch, 19 raw rows were found that had never reached `Events` at all —
ingested between 2026-06-23 and 2026-08-19 and dropped by the old `date`
window. A single `--days 72` run swept them in: **15 new events created, 8
existing events gained a source, 82 known events kept their stored
classification and cost no model call.** `Raw Events` now has zero unpromoted
rows, and `Events` went from 349 to 364.

That run also surfaced **5 groups of pre-existing duplicate events** — the same
government action written separately at different procedural stages, which the
old delete-and-rewrite path produced across weekly windows. The clusterer now
recognises each group as one event, but merging them would mean choosing whose
frozen text survives, so they are reported rather than merged. They need a
human call:

| state | event_ids | what it is |
|---|---|---|
| IL | `be021d9d…`, `199a55c9…` | Dept of Early Childhood launch, written twice |
| IL | `faaf4c6f…`, `4d664955…` | Pritzker AI-regulation signing |
| NC | `9d2c564d…`, `97edf5a8…` | the $34B budget: passed, then signed |
| VA | `8fda1904…`, `1671dfa1…` | SCC / Dominion data-centre rate action |
| VA | `88eb1e46…`, `fa8bcc32…`, `8cacc227…` | the $205B biennial budget, in three stages |

**Stragglers fixed, and the reported duplicates collapsed — 2026-09-03.**

- **Two windows, not one.** `--days` is now only the *trigger* window (which
  states have something unseen); the new `--context-days` (default 30) is the
  wider *clustering* window a triggered state is clustered against. A late
  article therefore meets siblings that have aged out of `--days` and attaches
  to their event instead of duplicating it. A/B on a real pair ingested six days
  apart: at `--context-days 16` the late article produced a **new** event; at
  `--context-days 30` it reported `+src` against the existing one, kept the
  stored text and cost no classify call. The daily workflow run inherits the
  30-day default. Quiet states are still skipped, so the wider context is free.
- **The 5 reported duplicate groups were collapsed into their latest stage**
  with the new `tools/collapse_state_events.py`, removing 6 rows. The survivor
  is the row with the greatest `date` — a bill is agreed, then passed, then
  signed, and the signing is the one worth keeping. The losers' sources are
  merged into the survivor *before* deletion, which matters: an orphaned source
  URL belongs to no event, so the next run would see it as unseen and re-create
  the row just removed. Verified afterwards that `Raw Events` still has zero
  unpromoted rows. Reviewer annotations are carried across rather than dropped.
  One judgment call is flagged in that tool's output — see below.

**Collapsing nests later rows under the FIRST iteration — 2026-09-03.** The
first pass of this tool kept the *latest stage* row and, briefly, re-synthesized
its text from all the merged sources. Both were wrong, and the second was
wronger: re-deriving text whenever coverage accumulates is exactly the churn the
freeze exists to prevent, and it produced an Illinois headline the user
(rightly) rejected.

The rule is now the same one the daily dedupe follows: **the earliest `date`
survives** (ties broken by whichever saw more sources), its text and competency
are kept untouched, and the later rows' sources nest under it. A later article
about an action already recorded is not a new judgment about it.

- The cost, stated plainly: the surviving headline describes the stage the
  action was at when FIRST seen. A budget first recorded as "the Assembly passed
  X" keeps that framing after the governor signs it. That is the intended trade
  — an event resurfacing week after week as coverage trickles in is worse than a
  slightly stale verb.
- `--resynthesize` remains as an explicit opt-out for the case where a first
  pass is genuinely wrong rather than merely early. It is not the default.
- `dedupe.synthesize_one` / `MERGE_PROMPT` back that flag. They read the
  ORIGINAL raw articles rather than the clean rows, and never downgrade a
  classified event to `none` — the classifier is not deterministic and the
  default web view hides competency-empty rows.

**The five groups collapsed earlier used the old latest-stage rule**, so in each
one the *later* row survived and the first was deleted. Re-running under the new
rule cannot undo that: the earlier rows are gone from `Events`. Their record ids
are listed below so they can be restored from Airtable's trash if wanted, after
which re-collapsing would keep the restored row.

| group | deleted (the first iteration) | record id |
|---|---|---|
| IL Early Childhood | `199a55c9…` 07-01 | `rec9l2E7TRJvFeAUA` |
| IL AI | `faaf4c6f…` 07-06 | `recrHvF2mG9zzWryo` |
| NC budget | `97edf5a8…` 06-30 | `rec04gEvfAdGASuXH` |
| VA SCC | `8fda1904…` 07-15 | `reclu9xo4ejjMZyk6` |
| VA budget | `fa8bcc32…` 06-22 | `recoJ7KS2ulEQA8zH` |
| VA budget | `8cacc227…` 06-19 | `recabVBuXmTw3l83p` |

The daily dedupe now also attaches an ambiguous cluster to whichever existing
event came first, rather than to whichever shares the most sources.

The migration script gained a guard at the same time. Step 2 mints an
`event_id` from a row's sources, and once events started accreting sources the
stored id legitimately diverged from `event_id_for(current urls)` — so a second
run would have rewritten the ids of 8 live events and split them from their own
history. It now only ever touches a legacy `uuid4` or a blank, and reports how
many it left alone.

Two gaps left open on purpose:

- Rows whose `date` the gate got *wrong* now promote instead of being silently
  dropped. One in the first window reads `2025-01-01` against an ingest date of
  2026-08-28 — a 604-day lag, almost certainly hallucinated. The web view sorts
  newest-first on `date`, so it lands at the bottom of the feed rather than
  nowhere at all.
- A straggler arriving more than `--days` after its siblings still mints a
  second row, because they have aged out of the window and it shares no URL with
  anything stored. Within-window stragglers attach correctly. Healing the late
  case needs a periodic `--days 21` pass; not scheduled. One live instance, a
  Maine labor agreement held as two rows dated 08-21 and 08-25.

### Digest: real recipients, and one message per person — 2026-08-31

`updates.recodingamerica.org` is verified, so the digest now sends from
`digest@updates.recodingamerica.org` to a real list.

- **Recipients moved to Airtable** (`Digest Recipients`), replacing
  `RECIPIENTS = ["atharv@recodingamerica.org"]`. Status-driven: only `active` is
  mailed, and unsubscribes are honoured by status rather than by deleting the row,
  because a deleted row reappears the next time someone re-imports a list.
  `get_recipients()` exits rather than returning empty — silence there would look
  like a successful send nobody received. v0.4 had deliberately isolated this
  function for exactly this swap, and nothing in the renderer changed.
- **Every recipient gets their own message**, via Resend's `/emails/batch`
  endpoint. The previous call passed the whole list as `to`, which put every
  subscriber's address in every subscriber's header. Harmless at one recipient,
  a privacy breach at forty. BCC would hide them but reads as a blast to spam
  filters and leaves no way to vary the body per person.
- **Unsubscribe**, which the per-recipient split is what makes possible: a
  `List-Unsubscribe` header so Gmail and Outlook show their own control (people
  use it instead of reporting spam), plus a footer link. Both are a `mailto:` —
  no web endpoint, no token scheme, no place for a bug to leak the list, and at
  this size processing by hand is honest. The upgrade path, when the list
  outgrows that, is a tokenised `/api/unsubscribe` route writing back to the
  table.
- `docs/digest-feature-brief.md` marked superseded rather than rewritten; its §0
  constraints (send only from `onboarding@resend.dev`, only to the account
  address) described a phase that is now over.

Verified by a real send to both seeded addresses.

### Digest: Governors '26 narrowed to the competitive races — 2026-08-31

The section ran two tiers — open-seat OR competitive at relevance >= 2, then
everything else at relevance 3 — and printed up to thirteen items, making the
2026 races the longest thing in an email whose state section is four
competencies. Now Toss-up and Lean only, relevance >= 2, five items, most
relevant first, with the overflow count linking to the candidates tab.
`race_type == "open"` no longer qualifies on its own: an open seat in a safe
state is still a safe state. On 30 days of live data, 5 shown and 6 held back.


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

## 2026-08-31 — Congress and Federal event validation sheets (hand-marked)

**Corpus.** Two sheets, committed as `data/Event Validation - Congress.csv` (111
rows) and `data/Event Validation - Federal.csv` (67 rows). Each row carries the
title, summary, why_it_matters, agency, competency, outlets and link the tracker
produced, plus three reviewer columns: include Y/N, good/bad/unclear for state
capacity, and free notes.

**Congress: the gate over-includes.** 111 rows marked, and the verdict was
**29 include, 70 exclude, 12 unsure** — roughly a quarter kept. The notes say
why, repeatedly and in the same words: *"Seems a bit out of scope"*, *"out of
scope"*, *"I don't think this fits in scope but I could be wrong"*, *"May be a
bit out of scope for state capacity"*, and on one bill *"Language is too
vague"*. The rejections are not misclassifications inside the four competencies;
they are events that should not have reached a competency at all. That points at
the congress gate prompt, not the dedupe or the rubric.

**Federal: mostly right, and the judgments are substantive.** 51 of 67 rows
marked, **32 include / 19 exclude**, with 31 good-bad-unclear calls written as
prose rather than a label — *"good (feedback loops!)"*, *"good (step in the right
direction toward making it easier to move in & out of civil service)"*, *"Good
(aligns with field proposals to use probationary periods as an evaluative tool +
streamline the appeals process)"*, against *"BAD"* on two and *"probably good;
the dismissal appeals process is a convoluted mess"* on another. 16 rows are
unmarked, so the federal inclusion rate is a floor, not a rate.

**Nothing has changed as a result yet. Still open.** The congress inclusion rate
is the actionable finding and no prompt, rubric or keyword list has moved on the
strength of it. Two things to be careful of when it is picked up: the
good/bad/unclear column is a *policy* judgment about the action, not a
relevance judgment about the row, so it must not be fed to a gate; and the
free-text column mixes both, as the *"see 53"* entry shows.

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
