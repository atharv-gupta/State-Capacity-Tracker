# Ecosystem Writing Tracker — Build Spec

A second, standalone pipeline that scrapes Recoding America's think-tank and nonprofit
partners' writing once a day into Airtable, for a new view/tab on the existing
tracker website. Sibling to the State Capacity Tracker, but **its own scripts
and its own table** — no merging with the state pipeline.

---

## 1. Goal

A daily RSS pull of curated partner outlets → one Airtable row per written
piece, enriched with author, a one-line summary, and topic tags → rendered as a
new "Ecosystem Writing" tab on the website (same render pattern as Events).

First deliverable is a **30-day backfill** to seed the table so the view has
content to design against. Daily cron comes after.

---

## 2. Scope (v1)

**In:** RSS-reachable partner outlets — Substacks, org blogs, and standard-CMS
publications (Tiers 1–2 from triage). All treated as trusted ("skim" mode):
no relevance gate, enrich everything that passes the content check.

**Out for v1 (explicit cuts):**
- Broad newspapers — NYT, Washington Post, The Atlantic.
- LinkedIn — the LinkedIn feed and the *Future State* LinkedIn newsletter
  (no clean RSS; auth-walled).
- NAPA *Management Matters* podcast (audio-only). NAPA's written
  *Academy Insights* stays in scope.

**The one gate — CONTENT.** Keep substantive written pieces (essay, report,
blog post, written news/analysis). Drop: audio/video-only items (podcast or
webinar with no article body), event listings, job postings,
donation/membership pages, and pure link roundups with no original writing.
Exception: an audio/video item *with* a real written companion article passes —
ingest the article.

---

## 3. Relationship to the State Capacity Tracker

Standalone module (e.g. `ecosystem/`), but **lift these helpers verbatim** from
`pipeline.py` rather than reinventing them:

- `parse_feed`, `entry_date`, `strip_html` — feed fetching/parsing.
- `parse_json_response` — robust JSON extraction from the model.
- `ensure_table`, `existing_source_urls` — Airtable bootstrap + URL dedup.
- The `ThreadPoolExecutor` classify pattern in `main`.

**Changes from the state pipeline:**
- New `ecosystem_sources.py` (§4) replaces `sources.py`.
- **No keyword pre-screen.** `PILLAR_KEYWORDS` / `PILLAR_PATTERNS` are gone —
  every source is skim, so there's no firehose to pre-filter.
- New system prompt: enrich + content-gate, not the two provenance/pillar gates.
- New `build_row` schema (§6).
- **No `dedupe.py`.** An essay appears once on its own feed; there's no
  cross-outlet coverage to cluster. URL-dedup in ingest is the whole dedup story.
- Shallow pagination only (§5).

Reuse env vars: `ANTHROPIC_API_KEY`, `AIRTABLE_TOKEN`, `AIRTABLE_BASE_ID`.
New table in the **same base** (decision flagged in §8). Model: `claude-haiku-4-5`.

---

## 4. Sources

### `ecosystem_sources.py`

Mirror `sources.py`: a list of dicts plus an `all_feeds()` generator yielding
`(org, feed_url, source_domain)`. Add a module docstring recording the
verification date, same discipline as the state registry's `2026-06-09` note.

```python
ECOSYSTEM_SOURCES = [
    {"org": "Slow Boring",  "feed_url": "https://www.slowboring.com/feed"},
    {"org": "Statecraft",   "feed_url": "https://www.statecraft.pub/feed"},
    {"org": "FedScoop",     "feed_url": "https://fedscoop.com/feed/"},
    # ...
]
```

### Task 0 — verification sweep (do this first)

The feed URLs below are **candidates, not verified.** Before writing the
registry, run a sweep: for each org, try the candidate URL, then fall back
through common patterns (`/feed`, `/feed/`, `/rss/`, `/rss.xml`,
`?format=rss`). Record which resolves to a valid feed with recent entries,
drop dead ones, and flag any org with **no working feed** for an
HTML-scrape decision (defer those to phase 2 — don't block v1 on them).

*(My build sandbox can only reach package registries, not the open web, so this
sweep has to run in Claude Code where bash has open egress.)*

**Substack-pattern (try `<root>/feed`):**
- Artificial Weights — https://artificialweights.substack.com/feed
- Art of Association — https://artofassociation.substack.com/feed
- IFP Substack — https://instituteforprogress.substack.com/feed
- Launchpad — https://horizonlaunchpad.substack.com/feed
- Slow Boring — https://www.slowboring.com/feed
- Statecraft — https://www.statecraft.pub/feed
- The Argument — https://www.theargumentmag.com/feed
- Eating Policy — https://www.eatingpolicy.com/feed
- Hypertext — https://hypertextmag.com/feed *(may be Ghost → `/rss/`)*

**Known / standard-CMS (try given URL or `<root>/feed/`):**
- Cato — https://www.cato.org/rss/blog *(URL confirmed by you)*
- FedScoop — https://fedscoop.com/feed/ *(same Scoop CMS as your live StateScoop feed)*
- American Affairs — https://americanaffairsjournal.org/feed/
- FAS Government Capacity — https://fas.org/issue/government-capacity/feed/
- Factory Settings — https://www.factorysettings.org/feed/
- Commonplace — https://www.commonplace.org/feed/
- Reboot Democracy — https://rebootdemocracy.ai/blog
- American Compass — https://americancompass.org/feed/
- USDR — https://www.usdigitalresponse.org/news-insights
- POPVOX — https://www.popvox.org/blog
- Roosevelt Institute — https://rooseveltinstitute.org/publications/
- IFP (org site) — https://ifp.org/latest-publications/
- FAI — https://www.thefai.org/american-governance
- Rainey Center — https://www.raineycenter.org/news
- Better Government Lab — https://www.bettergovernmentlab.org/publications
- American Governance Institute — https://americalabs.org/news/
- Partners in Public Innovation — https://www.publicinnovation.net/blog
- Credential Engine — https://credentialengine.org/all-resources/reports/
- Burnes Center — https://burnes.northeastern.edu/from-the-burnes-center
- Data Foundation — https://datafoundation.org/news
- Democracy Forward — https://democracyforward.org/news/
- IBM Center — https://www.businessofgovernment.org/blog
- Inclusive Abundance — https://www.inclusiveabundance.org/abundance-in-action
- SeedAI — https://www.seedai.org/project
- Stanford RegLab — https://reglab.stanford.edu/publications/
- Congressional Management Foundation — https://www.congressfoundation.org/news
- NAPA Academy Insights — https://napawash.org/academy-insights *(written only)*
- City Journal — https://www.city-journal.org/rss.xml
- Partnership for Public Service — https://ourpublicservice.org/blog/

**Broad-ish — flag, don't auto-include in skim:** Cato (blog), New America
(`/latest/`, `/the-thread/`), Manhattan Institute (`/articles`), R Street
(`/research-overview/`), National Affairs, Niskanen (`/state-capacity/`).
These publish across many topics, so pure skim mode will inject off-topic
items. Per source, the sweep should prefer the **narrowest section feed** that
exists; where only a whole-site feed exists, mark the org as needing a light
topical filter (phase 2) and either hold it back or accept the noise for now.
See §9 decision.

---

## 5. Pipeline stages — `ecosystem_pipeline.py`

1. **Fetch** every feed in `ecosystem_sources.all_feeds()` (threaded, reuse
   `parse_feed`).
2. **Date window** — keep entries with `pub_date >= today - days`.
   - *Pagination:* keep a **shallow** cap (`MAX_FEED_PAGES = 5`) using the same
     `?paged=N` backward-paging as the state pipeline, but only so the 30-day
     backfill reaches a full month on the busier feeds (Cato, FedScoop, the
     larger think tanks). Daily 7-day runs on slow feeds won't trigger it.
3. **URL dedup** — drop entries already in the table (`existing_source_urls`).
4. **Enrich + content-gate** (one LLM call per surviving entry, threaded, §6).
5. **Write** one row per kept piece to the `Ecosystem Writing` table.
6. Print a state-tracker-style summary (feeds / entries / in-window / kept /
   dropped / written).

---

## 6. LLM contract + Airtable schema

### System prompt (sketch)

> You enrich one piece of writing from a curated Recoding America partner outlet for the
> Ecosystem Writing tracker. The outlets are pre-trusted, so there is **no
> relevance gate**. Apply ONE gate — CONTENT: is this a substantive written
> piece (essay, report, blog post, written news/analysis)? FAIL it if the item
> is audio/video-only (podcast/webinar with no article text), an event listing,
> a job posting, a donation/membership page, or a pure link roundup with no
> original writing. An audio/video item WITH a real written companion article
> PASSES — treat the article as the piece.
>
> If it passes, output ONLY:
> ```json
> {"keep": true,
>  "title": "clean title",
>  "author": "author name(s), or \"\" if absent",
>  "piece_type": "essay | report | blog-post | news-analysis | other",
>  "topics": ["one or more of: procedure | digital | civil-service | state-capacity | govtech | public-admin"],
>  "summary": "one plain sentence, your own words, what the piece argues or reports"}
> ```
> If it fails, output ONLY: `{"keep": false, "reason": "one short line"}`
> No markdown fences, no preamble.

Topic taxonomy = your three pillars (`procedure`, `digital`, `civil-service`)
plus a wider set (`state-capacity`, `govtech`, `public-admin`) because
ecosystem writing ranges past the three pillars and you'll lose good pieces if
those are the only tags.

### `Ecosystem Writing` table — `REQUIRED_FIELDS`

| Field | Type | Notes |
|---|---|---|
| Name | singleLineText | `Org — title` |
| title | multilineText | cleaned title |
| org | singleLineText | from registry |
| author | singleLineText | from LLM, may be empty |
| url | singleLineText | dedup key |
| published | date (iso) | from feed |
| piece_type | singleSelect | essay / report / blog-post / news-analysis / other |
| topics | multipleSelects | taxonomy above |
| summary | multilineText | one-line LLM summary |
| source_domain | singleLineText | provenance |
| ingested_at | dateTime | run timestamp |

---

## 7. CLI

```
python ecosystem_pipeline.py            # daily, last 7 days
python ecosystem_pipeline.py --days 30  # the seed backfill
python ecosystem_pipeline.py --dry-run  # enrich but don't write
python ecosystem_pipeline.py --limit N  # cap items sent to the LLM
```

Default `--days 7` (forgiving of a missed cron run; URL dedup absorbs overlap).

---

## 8. Build order for Claude Code

0. **Verify feeds** (§4 Task 0) → write `ecosystem_sources.py` with a dated
   verification note.
1. **Build `ecosystem_pipeline.py`** — lift the §3 helpers, drop the
   pre-screen, swap in the enrich prompt and new schema, wire `ensure_table`
   to `Ecosystem Writing`.
2. **Seed run:** `python ecosystem_pipeline.py --days 30` → populate the table.
   Eyeball the rows; tune the content gate against whatever noise slips through.
3. **Website tab** — new "Ecosystem Writing" view reading the new table, same
   card/render pattern as Events. (Separate task; v1 can stop after the seed.)
4. **Daily cron** — GitHub Action on the existing schedule, `--days 7`.

---

## 9. Open decisions (resolve before / during build)

- **Same base or new base?** Spec assumes a new **table** in your existing
  `AIRTABLE_BASE_ID`. Switch to a separate base if you'd rather keep the
  ecosystem data fully isolated.
- **Broad-ish orgs (Cato, New America, Manhattan, R Street, National Affairs,
  Niskanen):** for v1, (a) hold them back, (b) include via narrowest section
  feed, or (c) include whole-site and accept off-topic noise until a phase-2
  topical filter. Recommend (b) where a section feed exists, (a) otherwise.
- **No-feed orgs** surfaced by the sweep: drop for v1 or queue for an
  HTML-scrape phase 2.
