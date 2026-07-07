# Gubernatorial Candidates Tracker — spec

A new layer of the State Tracker for the 2026 governor's races (36 states; likely
20+ new governors — the RAF transition-cycle opportunity described in the NGA
gubernatorial transition approach memo). Two jobs:

1. **Roster** — one row per primary winner / major contender, with a static,
   RAF-lens platform profile (what they've already said or done on our four
   competencies — e.g. Weiser's regulatory-reform record in CO).
2. **Developments** — an ongoing feed of RAF-relevant campaign developments
   (policy plans, press releases, speeches/quotes, interviews), classified
   against the same four competencies as the main tracker, but with a
   campaign-adapted gate: *governing agenda in, horse-race out*.

The main pipeline deliberately excludes campaign coverage (pipeline.py Gate 1),
so this is a standalone sibling — own scripts, own tables, own tab — following
the ecosystem tracker model (`ecosystem_pipeline.py`).

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
| platform_summary | long text | static-scrape output: RAF-lens summary of existing platform |
| competency_signals | multi-select | civil-service / procedure / digital / incentives |
| platform_sources | long text | one URL per line |
| platform_asof | date | when the platform scrape ran |
| notes | long text | |
| seeded_at | dateTime | |

### `Candidate Developments` (feed; pipeline-written)

`Name` (primary, `"CO — Weiser: day-one reg-reform EO"`), `candidate`, `state`,
`date`, `dev_type` (select: policy-plan / press-release / speech-quote /
interview / news-coverage / official-action / other), `headline`, `summary`,
`why_it_matters`, `competency` (multi-select, same four), `relevance` (1–3,
rubric.md scale), `quote` (long text — verbatim candidate quote when one
carries the story), `source_urls`, `source_outlets`, `url` (dedupe key),
`ingested_at`.

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

`.github/workflows/weekly.yml` gains a daily step
`python candidates_pipeline.py --days 7` (same secrets). The platform scrape is
run manually (it's static; re-run per candidate as races develop). After the
November election, flip `status` to elected/defeated and the roster becomes the
transition-tracking spine.

## Non-goals (for now)

Linked-record fields (text joins on `candidate`/`state` match the repo's
existing postal-join pattern); digest integration; polling/horse-race data.
