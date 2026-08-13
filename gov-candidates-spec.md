# Gubernatorial Candidates Tracker — spec

A new layer of the State Tracker for the 2026 governor's races (36 states; likely
20+ new governors — the Recoding America transition-cycle opportunity described in the NGA
gubernatorial transition approach memo). Two jobs:

1. **Roster** — one row per primary winner / major contender, with a static,
   RA-lens platform profile (what they've already said or done on our four
   competencies — e.g. Weiser's regulatory-reform record in CO).
2. **Developments** — an ongoing feed of RA-relevant campaign developments
   (policy plans, press releases, speeches/quotes, interviews), classified
   against the same four competencies as the main tracker, but with a
   campaign-adapted gate: *governing agenda in, horse-race out*.

The main pipeline deliberately excludes campaign coverage (pipeline.py Gate 1),
so this is a standalone sibling — own scripts, own tables, own tab — following
the ecosystem tracker model (`ecosystem_pipeline.py`).

### Two-layer architecture (mirrors the main tracker: raw ingest → weekly clean)

Developments run through the same raw→clean split as the main State Activity
Tracker (`pipeline.py` → `dedupe.py`), because campaign coverage is noisy and
duplicative (one Hobbs announcement lands as five near-identical articles):

- **Raw layer** — `candidates_pipeline.py` writes one row per ARTICLE to
  `Candidate Developments` behind a **two-gate** LLM screen (haiku): gate 1
  governing-agenda (horse-race out), gate 2 must touch ≥1 of the four
  competencies (most campaign coverage fails here — a tax/healthcare/crime plan
  with no bearing on how the state builds itself is dropped). Runs daily.
- **Clean layer** — `candidates_dedupe.py` (weekly, Mondays) clusters raw rows
  that describe the SAME development for ONE candidate into a single row in
  `Candidate Events`, merges sources, and **re-classifies with the full
  rubric.md** using a stronger model (sonnet). This second pass is where
  relevance is authoritatively assigned — exactly as `dedupe.py` does for the
  main tracker. Relevance is LLM-only (no human review field), and the web tab
  + (future) digest treat "has a competency + relevance ≥ 2" as RA-relevant.

Observed effect on the seed corpus: 87 raw articles → 41 developments, and the
sonnet re-classification cut the RA-relevant share from 82% (raw haiku) to 32%.

## Airtable tables

### `Gov Candidates` (roster; seeded, hand-curated thereafter)

| field | type | notes |
|---|---|---|
| Name | text (primary) | `"CO — Phil Weiser (D)"` |
| candidate | text | join key used by Candidate Developments |
| state | text | 2-letter postal — join key to State Specs / Events |
| party | select | R / D / I |
| status | select | incumbent / primary-winner / runoff-pending / presumptive-nominee / major-contender / withdrawn / elected / defeated |
| current_role | text | "Attorney General", "U.S. Rep" … |
| race_type | select | open / incumbent-running |
| race_rating | select | Safe R … Toss-up … Safe D (Cook/Sabato consensus) |
| primary_date | date | |
| primary_held | checkbox | |
| website | url | campaign site |
| press_url | url | campaign press/news page if distinct |
| news_query | text | optional override for the Google News RSS query |
| platform_summary | long text | static-scrape output: RA-lens summary of existing platform |
| competency_signals | multi-select | civil-service / procedure / digital / incentives |
| platform_sources | long text | one URL per line |
| platform_asof | date | when the platform scrape ran |
| notes | long text | |
| seeded_at | dateTime | |

### `Candidate Developments` (RAW feed; `candidates_pipeline.py`-written)

One row per ARTICLE. `Name` (primary, `"CO — Weiser: day-one reg-reform EO"`),
`candidate`, `state`, `date`, `dev_type` (select: policy-plan / press-release /
speech-quote / interview / news-coverage / official-action / other), `headline`,
`summary`, `why_it_matters`, `competency` (multi-select, same four — gate-2
signal), `relevance` (1–3), `quote` (long text — verbatim candidate quote when
one carries the story), `source_urls`, `source_outlets`, `url` (dedupe key),
`ingested_at`.

### `Candidate Events` (CLEAN feed; `candidates_dedupe.py`-written)

One row per DEVELOPMENT (raw rows about the same thing merged). Same core fields
as the raw table — `Name`, `event_id`, `candidate`, `state`, `date`, `dev_type`,
`headline`, `summary`, `why_it_matters`, `quote`, `competency`, `relevance`,
`topic_tags` (same set as the main Events table), `source_urls` (all members'
URLs), `source_outlets` (all members' outlets), plus `article_count` (how many
raw rows merged), `Status`, `deduped_at`. This is the table the web tab and the
future digest read. Rebuilt per weekly window (rows outside the window are never
touched), same as the main `Events` table.

## Scripts

- **`candidates_seed.py`** — reads `candidates_seed.json` (researched roster),
  ensures the `Gov Candidates` table, upserts on (candidate, state). Re-runnable;
  hand edits in Airtable to fields the JSON doesn't carry are preserved.
- **`candidates_pipeline.py`** — for every non-withdrawn candidate in
  `Gov Candidates`: builds a Google News RSS query (`news_query` override, else
  `"<name>" <state> governor`), plus `press_url`/RSS when present; date gate;
  URL-dedupe against the table; one Claude call per item (haiku, cached system
  prompt) that (a) confirms the item is substantively about the candidate's
  governing agenda/actions — dropping pure horse-race (polls, fundraising,
  attack ads, endorsements without policy content) — and (b) classifies
  competencies + relevance using rubric.md definitions adapted to candidates
  (statements/plans count, not just enacted actions; Principle 2
  direction-agnostic applies). Writes to `Candidate Developments`.
  Flags: `--days N`, `--dry-run`, `--limit N`, `--state XX`.
- **`candidates_dedupe.py`** — the clean layer (sibling of `dedupe.py`). Reads
  the last N days of `Candidate Developments`, clusters rows per candidate that
  describe the same development into one, merges sources, and re-classifies each
  against `rubric.md` (sent with a short candidate adaptation: a stated
  plan/pledge counts as an enacted action; Principle 1 & 2 unchanged) with
  sonnet. Rebuilds that window of `Candidate Events`. Flags: `--days N`,
  `--all`, `--state XX`, `--clean-table NAME`, `--dry-run`.
- **`candidate_platforms.py`** — the static scrape. Per candidate: fetch the
  campaign site, discover issue/platform pages (one hop, links matching
  issues|priorities|plan|policy|agenda), extract text (requests+bs4), combine
  with any `platform_sources` seed URLs, and run one sonnet call with the
  four-competency lens to produce `platform_summary` + `competency_signals` +
  `platform_sources`. Writes back to `Gov Candidates`, stamps `platform_asof`.
  Flags: `--state XX`, `--candidate NAME`, `--force` (re-scrape even if fresh),
  `--dry-run`.

## Web

- New tab **Governors '26** (`/candidates`): summary strip (races, open seats,
  competitive), filters (rating, party, status, competency signal), races
  grouped by state — race header (rating, open/incumbent, primary date/status)
  and candidate cards (party chip, role, status chip, competency chips,
  platform summary expander, website link). State name links to
  `/states/[postal]`.
- API routes `api/candidates` + `api/candidate-developments` (clones of
  `api/events/route.js`).
- State profile page (`states/[postal]/page.js`) gains a "2026 governor's race"
  card when the state has candidates — the reverse link.

## Ops

`.github/workflows/weekly.yml` runs `candidates_pipeline.py --days 7` **daily**
(the wide raw scrape) and `candidates_dedupe.py --days 7` on **Mondays** (gated
on the same day-of-week / manual-`dedupe`-input condition as the main
`dedupe.py`, and running right after it). Same secrets. The platform scrape is
run manually (it's static; re-run per candidate as races develop). After the
November election, flip `status` to elected/defeated and the roster becomes the
transition-tracking spine.

## Non-goals (for now)

Linked-record fields (text joins on `candidate`/`state` match the repo's
existing postal-join pattern); polling/horse-race data.

## Digest integration (done)

`digest.py` reads the clean `Candidate Events` table + the `Gov Candidates`
roster and appends a **Gov Candidates Corner** at the foot of the weekly email.
Selection is NOT grouped by competency (unlike the four state sections):
- **Priority** — developments in an open-seat OR competitive race (rating is a
  Toss-up or Lean), relevance ≥ 2;
- **Also notable elsewhere** — any other RA-relevant development at relevance 3.
Runs inside the existing Monday `digest.py --days 7` step, which now executes
after `candidates_dedupe.py` so the clean table is fresh. `load_candidate_devs`
tolerates a missing table (returns empty) so the digest still sends before the
first dedupe run.
